"""Station Operations: the full-day twin (live stream + one-shot what-if
runs), the daily truckfile with ferry-status refresh, and the Station
Operations Agent (investigations, learned playbook, recommendations sent
to the human-approval queue).

Thin wrappers only (CLAUDE.md): logic lives in app/simulation/station_ops,
app/agents/station_ops, app/inbound and app/security/station_ops_decisions.
Presets are looked up in a fixed allow-list, never a filesystem path.
"""

import json
import time
import uuid
from collections.abc import Iterator
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.station_ops import playbook
from app.agents.station_ops.agent import AGENT, StationOpsAgentInput
from app.agents.station_ops.counterfactual import SCORE_VERSION, SCORE_WEIGHTS
from app.agents.station_ops.detectors import Risk
from app.agents.station_ops.mitigations import LEVER_LIMITS
from app.agents.station_ops.stream import iter_frames
from app.core.config import get_settings
from app.core.llm.ollama import OllamaProvider
from app.db.postgres import SessionLocal, get_db
from app.inbound import service as inbound
from app.inbound.ferry import SyntheticFerryStatusProvider
from app.orchestration import repository
from app.orchestration.runner import AgentExecutor
from app.schemas.agents import AgentExecutionDetail, AgentExecutionSummary
from app.security import station_ops_decisions
from app.simulation.station_ops.config import StationOpsConfig
from app.simulation.station_ops.model import Intervention
from app.simulation.station_ops.plan import build_preset, list_presets
from app.simulation.station_ops.snapshot import (
    METRIC_DEFINITIONS,
    StationOpsSnapshot,
    run_station_day,
)

router = APIRouter(tags=["station-ops"])

Source = Literal["preset", "truckfile"]


def _config(
    db: Session | None, preset: str, seed: int, source: Source, ofd_date: date | None
) -> StationOpsConfig:
    try:
        cfg = build_preset(preset, seed)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if source == "truckfile":
        if db is None or ofd_date is None:
            raise HTTPException(status_code=422, detail="ofd_date is required for source=truckfile")
        trips = inbound.get_truckfile(db, ofd_date)
        if not trips:
            raise HTTPException(
                status_code=404, detail=f"no truckfile for {ofd_date}; refresh it first"
            )
        cfg.linehauls = inbound.to_linehaul_plans(trips)
        cfg.ofd_date = ofd_date
        cfg.source = "truckfile"
        cfg.name = f"truckfile_{ofd_date.isoformat()}"
        cfg.description = f"Linehaul plan and ferry delays from the {ofd_date} truckfile."
    return cfg


# --- twin ----------------------------------------------------------------------


@router.get("/station-ops/presets")
def presets() -> list[dict]:
    return list_presets()


@router.get("/station-ops/metric-definitions")
def metric_definitions() -> dict:
    return {
        "metrics": METRIC_DEFINITIONS,
        "score_weights": SCORE_WEIGHTS,
        "score_version": SCORE_VERSION,
        "lever_limits": LEVER_LIMITS,
    }


class RunDayRequest(BaseModel):
    preset: str = "normal_day"
    seed: int = 1
    source: Source = "preset"
    ofd_date: date | None = None
    interventions: list[Intervention] = Field(default=[], max_length=10)


@router.post("/station-ops/run-day", response_model=StationOpsSnapshot)
def run_day(request: RunDayRequest, db: Session = Depends(get_db)) -> StationOpsSnapshot:
    """One-shot what-if: the whole day with an optional manual lever plan."""
    from app.security.policy_engine import evaluate_station_ops

    if request.interventions:
        policy = evaluate_station_ops(
            [{"name": "manual", "interventions": [i.model_dump() for i in request.interventions]}]
        )
        if not policy.eligible:
            raise HTTPException(status_code=422, detail=policy.violations)
    cfg = _config(db, request.preset, request.seed, request.source, request.ofd_date)
    return run_station_day(cfg, request.interventions)


@router.get("/station-ops/live", response_class=StreamingResponse)
def live(
    preset: str = "ferry_disruption",
    seed: int = 1,
    mode: Literal["observe", "advise", "autopilot"] = "advise",
    source: Source = "preset",
    ofd_date: date | None = None,
    learn: bool = True,
    step_minutes: float = Query(5, ge=1, le=60),
    frame_interval_ms: int = Query(250, ge=0, le=2000),
) -> StreamingResponse:
    """SSE stream: `event: frame` ({snapshot, agent}) until every route has
    departed, then `event: end`. Bounded by MAX_FRAMES. With learn=true the
    agent's counterfactual evaluations are written to its playbook."""
    if source == "truckfile":
        with SessionLocal() as db:
            cfg = _config(db, preset, seed, source, ofd_date)
    else:
        cfg = _config(None, preset, seed, source, ofd_date)

    def frames() -> Iterator[str]:
        for frame in iter_frames(
            cfg,
            step_minutes=step_minutes,
            mode=mode,
            session_factory=SessionLocal if learn and mode != "observe" else None,
        ):
            yield f"event: frame\ndata: {json.dumps(frame)}\n\n"
            if frame_interval_ms and not frame["snapshot"]["done"]:
                time.sleep(frame_interval_ms / 1000)
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- truckfile / ferry ------------------------------------------------------------


class TruckfileRefreshRequest(BaseModel):
    ofd_date: date
    weather: Literal["calm", "rough", "severe"] | None = None
    seed: int = 1


def _trip_out(t) -> dict:
    return {
        "trip_id": t.trip_id,
        "origin": t.origin,
        "via_ferry": t.via_ferry,
        "ferry_sailing": t.ferry_sailing,
        "planned_arrival": t.planned_arrival.isoformat(),
        "revised_arrival": t.revised_arrival.isoformat() if t.revised_arrival else None,
        "volume": t.volume,
        "cycle": t.cycle,
        "ferry_status": t.ferry_status,
        "delay_minutes": t.delay_minutes,
        "delay_reason": t.delay_reason,
        "last_checked_at": t.last_checked_at.isoformat() if t.last_checked_at else None,
        "checks": len(t.ferry_checks or []),
        "source_kind": t.source_kind,
    }


@router.get("/inbound/truckfile")
def truckfile(ofd_date: date, db: Session = Depends(get_db)) -> dict:
    trips = inbound.get_truckfile(db, ofd_date)
    return {
        "ofd_date": ofd_date.isoformat(),
        "exists": bool(trips),
        "trips": [_trip_out(t) for t in trips],
    }


@router.post("/inbound/truckfile/refresh")
def refresh_truckfile(request: TruckfileRefreshRequest, db: Session = Depends(get_db)) -> dict:
    """The daily job: create the day's truckfile if missing, then check every
    ferry-borne trip against the ferry-status provider and write revised ETAs."""
    try:
        inbound.ensure_truckfile(db, request.ofd_date, seed=request.seed)
        summary = inbound.refresh_ferry_status(
            db,
            request.ofd_date,
            SyntheticFerryStatusProvider(seed=request.seed, force_weather=request.weather),
        )
    except Exception:
        db.rollback()
        raise
    db.commit()
    trips = inbound.get_truckfile(db, request.ofd_date)
    return {"summary": summary, "trips": [_trip_out(t) for t in trips]}


# --- agent ------------------------------------------------------------------------


class StationOpsRunRequest(BaseModel):
    preset: str = "ferry_disruption"
    seed: int = 1
    source: Source = "preset"
    ofd_date: date | None = None
    until_minute: float = Field(1440, ge=60, le=1440)
    propose_decisions: bool = True


@router.get("/agents/station-ops/executions", response_model=list[AgentExecutionSummary])
def list_station_ops_executions(db: Session = Depends(get_db)):
    return [
        AgentExecutionSummary.model_validate(e)
        for e in repository.list_executions(db, agent_name=AGENT.name)
    ]


@router.get("/agents/station-ops/executions/{execution_id}", response_model=AgentExecutionDetail)
def get_station_ops_execution(execution_id: uuid.UUID, db: Session = Depends(get_db)):
    e = repository.get_by_id(db, execution_id)
    if e is None or e.agent_name != AGENT.name:
        raise HTTPException(status_code=404, detail=f"no execution found for id={execution_id}")
    return AgentExecutionDetail.model_validate(e)


@router.post("/agents/station-ops/run")
def run_station_ops_agent(request: StationOpsRunRequest, db: Session = Depends(get_db)) -> dict:
    """Runs the agent over the day (advise mode), persists the execution,
    records its evaluations in the playbook, and sends each recommended plan
    to the approval queue as a PENDING_APPROVAL decision."""
    cfg = _config(db, request.preset, request.seed, request.source, request.ofd_date)
    settings = get_settings()
    llm = OllamaProvider(
        settings.ollama_base_url, settings.ollama_model, settings.ollama_keep_alive
    )
    inp = StationOpsAgentInput(
        preset=request.preset,
        seed=request.seed,
        until_minute=request.until_minute,
        linehauls=cfg.linehauls if request.source == "truckfile" else None,
        source="truckfile" if request.source == "truckfile" else "synthetic_plan",
    )
    try:
        output = AgentExecutor(db, llm).run(AGENT, inp)
        execution = repository.list_executions(db, agent_name=AGENT.name)[0]
        decision_ids = []
        for action in output.actions:
            if action.get("evaluations"):
                playbook.record(
                    db,
                    Risk.model_validate(action["risk"]),
                    [_ev(e) for e in action["evaluations"]],
                    scenario=cfg.name,
                    seed=cfg.seed,
                )
            if request.propose_decisions and action.get("chosen") and action.get("evaluations"):
                rec = station_ops_decisions.propose_from_action(
                    db,
                    action=action,
                    preset=request.preset,
                    seed=request.seed,
                    agent_execution_id=str(execution.id),
                )
                decision_ids.append(str(rec.id))
        if decision_ids:
            execution.output = {**(execution.output or {}), "decision_ids": decision_ids}
    except Exception:
        db.rollback()
        raise
    db.commit()
    return {
        "execution": AgentExecutionDetail.model_validate(execution).model_dump(mode="json"),
        "decision_ids": decision_ids,
    }


def _ev(e: dict):
    from app.agents.station_ops.counterfactual import Evaluation

    return Evaluation.model_validate(e)


@router.get("/agents/station-ops/playbook")
def get_playbook(risk_type: str | None = None, db: Session = Depends(get_db)) -> dict:
    stats = playbook.learned_effectiveness(db, risk_type)
    return {
        "episodes": sum(s["episodes"] for s in stats),
        "stats": stats,
        "note": "Learned from simulated counterfactual episodes only — "
        "not evidence about a real station.",
    }


@router.get("/llm/status")
def llm_status() -> dict:
    s = get_settings()
    llm = OllamaProvider(s.ollama_base_url, s.ollama_model, s.ollama_keep_alive)
    return {
        "provider": "ollama",
        "model": s.ollama_model,
        "base_url": s.ollama_base_url,
        "available": llm.is_available(),
    }
