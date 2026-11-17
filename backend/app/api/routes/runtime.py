"""Live station runtime API (ADR-0012): sessions, live state for every page,
controls, actions/coordination, agent recommendations, chat and search.

Thin wrappers over app/runtime. Presets come from the fixed allow-list; a
truckfile session reads its linehaul plan from Postgres here (the API layer)
and passes it into the twin as plain config — the twin never reads a
database. Every action is bounded by the policy engine's lever limits.
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.station_ops.mitigations import LEVER_LIMITS
from app.core.config import get_settings
from app.core.llm.ollama import OllamaProvider
from app.db.postgres import SessionLocal
from app.inbound import service as inbound
from app.runtime.chat import StationAssistant
from app.runtime.session import StationSession, manager
from app.simulation.station_ops.model import Intervention
from app.simulation.station_ops.plan import build_preset
from app.simulation.station_ops.views import city_map, driver_path
from app.simulation.station_ops.views import search as search_twin

router = APIRouter(prefix="/runtime", tags=["runtime"])

_DISRUPTION_CAPS = {
    "line_jam": 180,
    "scanner_degradation": 5,
    "absenteeism": 6,
    "traffic_incident": 60,
    "weather": 4,
    "volume_surge": 2000,
}


def _session(session_id: str) -> StationSession:
    s = manager.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"no session {session_id!r}")
    return s


class CreateSession(BaseModel):
    preset: str = "normal_day"
    seed: int | None = None
    mode: Literal["observe", "advise", "autopilot"] = "autopilot"
    speed: float = Field(2.0, ge=0.25, le=60)
    #: next_day: continue from the default session's close-out (its final truckfile)
    source: Literal["preset", "truckfile", "next_day"] = "preset"
    ofd_date: date | None = None
    #: Site-profile volume scale (routes and labour scale with it), bounded.
    scale: float = Field(1.0, ge=0.5, le=3.0)


@router.get("/sessions")
def list_sessions() -> list[dict]:
    return manager.list()


@router.post("/sessions")
def create_session(req: CreateSession) -> dict:
    try:
        cfg = build_preset(req.preset, req.seed or 1, req.ofd_date or date.today(), scale=req.scale)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if req.seed is None:
        cfg = None  # let the manager draw a fresh seed (a new day every time)
    if req.source == "next_day":
        prev = manager.default()
        with prev.lock:
            try:
                cfg = prev.twin.closeout.next_day_config()
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
    if req.source == "truckfile":
        if req.ofd_date is None:
            raise HTTPException(status_code=422, detail="ofd_date is required for source=truckfile")
        with SessionLocal() as db:
            trips = inbound.get_truckfile(db, req.ofd_date)
        if not trips:
            raise HTTPException(status_code=404, detail=f"no truckfile for {req.ofd_date}")
        cfg = build_preset(req.preset, req.seed or 1, req.ofd_date)
        cfg.linehauls = inbound.to_linehaul_plans(trips)
        cfg.source, cfg.name = "truckfile", f"truckfile_{req.ofd_date.isoformat()}"
    s = manager.create(
        req.preset, seed=req.seed, mode=req.mode, speed=req.speed, config=cfg, scale=req.scale
    )
    return s.info()


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    return _session(session_id).info()


@router.get("/sessions/{session_id}/state")
def state(session_id: str) -> dict:
    return _session(session_id).state()


class Control(BaseModel):
    paused: bool | None = None
    speed: float | None = Field(None, ge=0.25, le=60)
    mode: Literal["observe", "advise", "autopilot"] | None = None


@router.post("/sessions/{session_id}/control")
def control(session_id: str, req: Control) -> dict:
    return _session(session_id).control(**req.model_dump(exclude_none=True))


def _check(iv: Intervention) -> None:
    if iv.kind == "inject_disruption":
        kind = (iv.params or {}).get("kind", iv.target)
        if kind not in _DISRUPTION_CAPS:
            raise HTTPException(status_code=422, detail=f"unknown disruption {kind!r}")
        mag = float((iv.params or {}).get("magnitude", iv.amount))
        if not 0 < mag <= _DISRUPTION_CAPS[kind]:
            raise HTTPException(status_code=422, detail=f"{kind} magnitude out of bounds")
        return
    limit = LEVER_LIMITS.get(iv.kind)
    if limit is None or not 0 <= iv.amount <= limit:
        raise HTTPException(
            status_code=422, detail=f"{iv.kind} amount {iv.amount} outside (0, {limit}]"
        )


@router.post("/sessions/{session_id}/actions")
def act(session_id: str, iv: Intervention) -> dict:
    _check(iv)
    return _session(session_id).act(iv.model_copy(update={"source": iv.source or "manual"}))


@router.post("/sessions/{session_id}/recommendations/{action_id}/{verb}")
def decide(session_id: str, action_id: int, verb: Literal["approve", "dismiss"]) -> dict:
    s = _session(session_id)
    try:
        a = s.approve(action_id) if verb == "approve" else s.dismiss(action_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return a.model_dump(mode="json")


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)


_llm_cache: dict = {}


def _llm():
    s = get_settings()
    if "p" not in _llm_cache:
        _llm_cache["p"] = OllamaProvider(s.ollama_base_url, s.ollama_model, s.ollama_keep_alive)
    p = _llm_cache["p"]
    return p if p.is_available() else None


@router.post("/sessions/{session_id}/chat")
def chat(session_id: str, req: ChatIn) -> dict:
    s = _session(session_id)
    return StationAssistant(s, _llm()).handle(req.message).model_dump(mode="json")


@router.get("/sessions/{session_id}/chat")
def chat_history(session_id: str) -> list[dict]:
    return _session(session_id).chat_history[-100:]


@router.get("/sessions/{session_id}/search")
def search(session_id: str, q: str = "") -> dict:
    s = _session(session_id)
    with s.lock:
        return search_twin(s.twin, q[:40])


@router.get("/sessions/{session_id}/map")
def station_map(session_id: str) -> dict:
    """Static geometry of the fictional delivery area (roads, river, zones)."""
    s = _session(session_id)
    with s.lock:
        return city_map(s.twin)


@router.get("/sessions/{session_id}/drivers/{driver_id}/path")
def path(session_id: str, driver_id: str) -> dict:
    s = _session(session_id)
    with s.lock:
        out = driver_path(s.twin, driver_id[:20])
    if out is None:
        raise HTTPException(status_code=404, detail="no such driver")
    return out


class AckIn(BaseModel):
    audience: Literal["supervisor", "manager", "dsp", "all"] = "all"


@router.post("/sessions/{session_id}/notifications/{notification_id}/ack")
def ack(session_id: str, notification_id: int) -> dict:
    n = _session(session_id).ack(notification_id)
    if n is None:
        raise HTTPException(status_code=404, detail="no such notification")
    return n


@router.post("/sessions/{session_id}/notifications/ack-all")
def ack_all(session_id: str, req: AckIn) -> dict:
    return {"acked": _session(session_id).ack_all(req.audience)}


# --- v2: chapters / seek, settings, work items, drill-down lists, shift report ------------


class SeekIn(BaseModel):
    minute: float = Field(..., ge=0, le=1380)


@router.post("/sessions/{session_id}/seek")
def seek(session_id: str, req: SeekIn) -> dict:
    return _session(session_id).seek(req.minute)


class SettingsIn(BaseModel):
    stow_wip_lower_min: float | None = Field(None, ge=1, le=120)
    stow_wip_upper_min: float | None = Field(None, ge=2, le=180)
    stow_wip_compliance_target: float | None = Field(None, ge=0, le=1)
    induct_dwell_minutes: float | None = Field(None, ge=10, le=240)


@router.patch("/sessions/{session_id}/settings")
def update_settings(session_id: str, req: SettingsIn) -> dict:
    try:
        return _session(session_id).update_settings(req.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/work-items/{item_id}/{verb}")
def work_item(session_id: str, item_id: str, verb: Literal["complete", "dismiss"]) -> dict:
    s = _session(session_id)
    if item_id.startswith("REC-"):
        try:
            a = s.approve(int(item_id[4:])) if verb == "complete" else s.dismiss(int(item_id[4:]))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "id": item_id,
            "state": "done" if verb == "complete" else "dismissed",
            "action": a.id,
        }
    try:
        return s.work_item(item_id, verb)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/packages")
def packages(
    session_id: str,
    group: str,
    status: str | None = None,
    column: str | None = None,
    by: Literal["cycle", "window"] = "cycle",
) -> dict:
    return _session(session_id).packages(group, status, column, by)


@router.get("/sessions/{session_id}/report")
def report(session_id: str) -> dict:
    return _session(session_id).report()
