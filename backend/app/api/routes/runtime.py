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
    source: Literal["preset", "truckfile"] = "preset"
    ofd_date: date | None = None


@router.get("/sessions")
def list_sessions() -> list[dict]:
    return manager.list()


@router.post("/sessions")
def create_session(req: CreateSession) -> dict:
    try:
        cfg = build_preset(req.preset, req.seed or 1, req.ofd_date or date.today())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if req.seed is None:
        cfg = None  # let the manager draw a fresh seed (a new day every time)
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
    s = manager.create(req.preset, seed=req.seed, mode=req.mode, speed=req.speed, config=cfg)
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
