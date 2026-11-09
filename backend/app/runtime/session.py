"""StationSession — one live simulated operating day, advanced by a
background thread, with the multi-agent orchestrator running on its own
thread beside it.

Concurrency: SimPy is not thread-safe, so every read or write of the twin
happens under `self.lock` (an RLock). The orchestrator holds it only to read
state and apply actions; its counterfactual simulations run outside the
lock, so the day keeps moving while agents think and their decisions land at
the (later) minute they finish — decision latency, as in a real station.
"""

import random
import threading
import time
import uuid
from datetime import UTC, date, datetime

from app.agents.station_ops.loop import AgentAction, Mode, StationOpsAgentLoop
from app.simulation.station_ops.config import StationOpsConfig
from app.simulation.station_ops.model import (
    DAY_END_MINUTE,
    Intervention,
    StationOpsTwin,
)
from app.simulation.station_ops.plan import build_preset
from app.simulation.station_ops.snapshot import build_snapshot
from app.simulation.station_ops.views import build_views

START_MINUTE = 60.0
TICK_SECONDS = 0.25
AGENT_EVERY_MINUTES = 15.0
MAX_SESSIONS = 3
MAX_THINK_MINUTES = 5.0


class StationSession:
    def __init__(
        self,
        config: StationOpsConfig,
        *,
        mode: Mode = "autopilot",
        speed: float = 2.0,
        session_factory=None,
        futures: int = 2,
    ):
        self.id = uuid.uuid4().hex[:8]
        self.config = config
        self.created_at = datetime.now(UTC)
        self.lock = threading.RLock()
        self.twin = StationOpsTwin(config)
        self.twin.run_until(START_MINUTE)
        self.loop = StationOpsAgentLoop(mode, session_factory, futures=futures, lock=self.lock)
        self.speed = speed  # simulated minutes per wall-clock second
        self.paused = False
        self.agent_busy = False
        self.chat_history: list[dict] = []
        self._stop = threading.Event()
        self._next_agent = START_MINUTE
        self._agent_started = START_MINUTE
        self._cache: tuple[float, dict] | None = None
        self._sim_thread = threading.Thread(
            target=self._run_sim, daemon=True, name=f"sim-{self.id}"
        )
        self._agent_thread = threading.Thread(
            target=self._run_agents, daemon=True, name=f"agents-{self.id}"
        )
        self._sim_thread.start()
        self._agent_thread.start()

    # --- threads -----------------------------------------------------------------

    @property
    def complete(self) -> bool:
        return self.twin.day_complete or self.twin.now_minute >= DAY_END_MINUTE

    def _run_sim(self) -> None:
        while not self._stop.is_set():
            time.sleep(TICK_SECONDS)
            if self.paused or self.complete:
                continue
            if self.agent_busy and self.twin.now_minute >= self._agent_started + MAX_THINK_MINUTES:
                # Bounded decision latency: the station keeps moving while the
                # agents plan, but never more than a few simulated minutes —
                # at 30x playback, wall-clock think time would otherwise
                # become hours of simulated delay.
                continue
            with self.lock:
                self.twin.run_until(
                    min(DAY_END_MINUTE, self.twin.now_minute + self.speed * TICK_SECONDS)
                )

    def _run_agents(self) -> None:
        while not self._stop.is_set():
            time.sleep(0.2)
            if self.paused or self.complete:
                continue
            with self.lock:
                due = self.twin.now_minute >= self._next_agent and not self.twin.done
                snap = build_snapshot(self.twin, 0) if due else None
            if not due:
                continue
            self._agent_started = self.twin.now_minute
            self.agent_busy = True
            try:
                self.loop.step(self.twin, snap)
            finally:
                self.agent_busy = False
                with self.lock:
                    self._next_agent = self.twin.now_minute + AGENT_EVERY_MINUTES

    def stop(self) -> None:
        self._stop.set()

    # --- state ---------------------------------------------------------------------

    def state(self) -> dict:
        """Full live state (snapshot + every page view), cached per sim minute."""
        with self.lock:
            key = round(self.twin.now_minute, 2)
            if self._cache and self._cache[0] == key:
                cached = self._cache[1]
            else:
                snap = build_snapshot(self.twin, 0).model_dump(mode="json")
                cached = {"snapshot": snap, "views": build_views(self.twin, snap)}
                self._cache = (key, cached)
            risks = [r.model_dump(mode="json") for r in self.loop.current_risks]
        return {
            **cached,
            "session": self.info(),
            "agents": {
                "mode": self.loop.mode,
                "busy": self.agent_busy,
                "risks": risks,
                "actions": [a.model_dump(mode="json") for a in self.loop.actions[-60:]],
                "pending": [
                    a.model_dump(mode="json") for a in self.loop.actions if a.status == "pending"
                ][-20:],
            },
        }

    def info(self) -> dict:
        return {
            "id": self.id,
            "preset": self.config.name,
            "seed": self.config.seed,
            "description": self.config.description,
            "ofd_date": self.config.ofd_date.isoformat(),
            "mode": self.loop.mode,
            "speed": self.speed,
            "paused": self.paused,
            "complete": self.complete,
            "minute": self.twin.now_minute,
            "created_at": self.created_at.isoformat(),
            "source": self.config.source,
        }

    # --- control & actions -----------------------------------------------------------

    def control(
        self, *, paused: bool | None = None, speed: float | None = None, mode: Mode | None = None
    ) -> dict:
        if paused is not None:
            self.paused = paused
        if speed is not None:
            self.speed = max(0.25, min(60.0, speed))
        if mode is not None:
            self.loop.mode = mode
        return self.info()

    def act(self, iv: Intervention) -> dict:
        with self.lock:
            rec = self.twin.apply(iv.model_copy(update={"at_minute": self.twin.now_minute}))
            self._cache = None
        return rec

    def find_action(self, action_id: int) -> AgentAction | None:
        return next((a for a in self.loop.actions if a.id == action_id), None)

    def approve(self, action_id: int) -> AgentAction:
        a = self.find_action(action_id)
        if a is None or a.status != "pending":
            raise ValueError(f"no pending recommendation #{action_id}")
        with self.lock:
            for iv in a.chosen_interventions:
                rec = self.twin.apply(
                    iv.model_copy(
                        update={"at_minute": self.twin.now_minute, "source": "human_approved"}
                    )
                )
                a.applied_effects.append(rec["effect"])
            self._cache = None
        a.applied, a.status = True, "applied"
        return a

    def dismiss(self, action_id: int) -> AgentAction:
        a = self.find_action(action_id)
        if a is None or a.status != "pending":
            raise ValueError(f"no pending recommendation #{action_id}")
        a.status = "dismissed"
        return a


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, StationSession] = {}
        self._default: str | None = None
        self._lock = threading.Lock()
        self.session_factory = None

    def create(
        self,
        preset: str = "normal_day",
        *,
        seed: int | None = None,
        mode: Mode = "autopilot",
        speed: float = 2.0,
        config: StationOpsConfig | None = None,
        make_default: bool = True,
    ) -> StationSession:
        if seed is None:
            # A fresh day every time — different arrivals, absences, drivers, friction.
            seed = random.SystemRandom().randrange(1, 100_000)
        cfg = config or build_preset(preset, seed, date.today())
        s = StationSession(cfg, mode=mode, speed=speed, session_factory=self.session_factory)
        with self._lock:
            self._sessions[s.id] = s
            if make_default or self._default is None:
                self._default = s.id
            while len(self._sessions) > MAX_SESSIONS:
                oldest = next(k for k in self._sessions if k != self._default)
                self._sessions.pop(oldest).stop()
        return s

    def get(self, session_id: str) -> StationSession | None:
        if session_id == "default":
            return self.default()
        return self._sessions.get(session_id)

    def default(self) -> StationSession:
        with self._lock:
            sid = self._default
        if sid and sid in self._sessions:
            return self._sessions[sid]
        return self.create()

    def list(self) -> list[dict]:
        return [s.info() | {"default": s.id == self._default} for s in self._sessions.values()]

    def stop_all(self) -> None:
        for s in self._sessions.values():
            s.stop()
        self._sessions.clear()
        self._default = None


manager = SessionManager()
