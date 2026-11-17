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
    clock,
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
        #: assistant memory: last topic (for follow-ups), cached replays
        self.chat_context: dict = {}
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
                # sudden events (wrong staging scan, grounded van, truckfile
                # revision...) wake the agents early instead of waiting a cycle
                due = (
                    self.twin.now_minute >= self._next_agent or self.twin.urgent
                ) and not self.complete
                self.twin.urgent = False
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
            # agent recommendations waiting for a person are work items too (E10)
            # pending ones, plus ones a person already decided (kept visible as done/dismissed)
            pending = [
                a
                for a in self.loop.actions
                if a.status == "pending"
                or (a.status in ("dismissed", "applied") and a.decided_by_person)
            ][-30:]
            recs = [
                {
                    "id": f"REC-{a.id}",
                    "kind": "agent_recommendation",
                    "category": "Ops Updates",
                    "process": a.agent_label,
                    "priority": 1 if a.risk.severity == "critical" else 2,
                    "title": f"{a.agent_label}: {a.chosen}",
                    "owner": "manager",
                    "associate": None,
                    "started_by": "agent",
                    "ref": str(a.id),
                    "created": a.minute,
                    "created_clock": a.clock,
                    "expires_at": a.minute + 30,
                    "expires_clock": clock(a.minute + 30),
                    "state": (
                        "dismissed"
                        if a.status == "dismissed"
                        else "done"
                        if a.status == "applied"
                        else "pending"
                        if self.twin.now_minute < a.minute + 30
                        else "expired"
                    ),
                    "recommendation_id": a.id,
                }
                for a in pending
            ]
        views = dict(cached["views"])
        if recs:
            wi = dict(views.get("work_items_v2", {}))
            wi["items"] = recs + list(wi.get("items", []))
            summ = dict(wi.get("summary", {}))
            summ["pending"] = summ.get("pending", 0) + sum(
                1 for r in recs if r["state"] == "pending"
            )
            summ["agent_recommendations"] = len(recs)
            summ["dismissed_today"] = summ.get("dismissed_today", 0) + sum(
                1 for r in recs if r["state"] == "dismissed"
            )
            summ["completed_today"] = summ.get("completed_today", 0) + sum(
                1 for r in recs if r["state"] == "done"
            )
            wi["summary"] = summ
            views["work_items_v2"] = wi
        return {
            **cached,
            "views": views,
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

    # --- v2: chapters / seek, settings, work items, drill-down, report ------------------

    def seek(self, minute: float) -> dict:
        """Jump to a sim minute. Forward: fast-forward with the agents stepping
        every 30 sim minutes on reflexes only (planned, simulated decisions
        resume when the jump lands).
        Backward: deterministic replay of the config plus every action taken
        before that minute (the twin is replayable by design)."""
        minute = max(0.0, min(DAY_END_MINUTE, minute))
        was_paused = self.paused
        self.paused = True
        try:
            with self.lock:
                now = self.twin.now_minute
                if minute < now:
                    log = [
                        Intervention(
                            kind=a["kind"],
                            amount=a["amount"],
                            at_minute=a["minute"],
                            target=a.get("target"),
                            params=a.get("params") or {},
                            source=a["source"],
                        )
                        for a in self.twin.applied
                        if a["minute"] < minute and not a["source"].startswith("disruption")
                    ]
                    self.twin = StationOpsTwin(self.config, log)
                    self.twin.run_until(minute)
                    self.loop.actions = [a for a in self.loop.actions if a.minute < minute]
                    self.loop._last = {}
                    self._cache = None
                    return self.info() | {"seek": "replayed"}
            t = now
            while t < minute and not self.twin.day_complete:
                t = min(minute, t + 30)
                with self.lock:
                    self.twin.run_until(t)
                    snap = build_snapshot(self.twin, 0)
                    self.twin.urgent = False
                self.loop.reflex_only = True
                try:
                    self.loop.step(self.twin, snap)
                finally:
                    self.loop.reflex_only = False
            with self.lock:
                self._next_agent = self.twin.now_minute + AGENT_EVERY_MINUTES
                self._cache = None
            return self.info() | {"seek": "forward"}
        finally:
            self.paused = was_paused

    def update_settings(self, values: dict) -> dict:
        from app.simulation.station_ops.views_v2 import EDITABLE_SETTINGS

        bad = [k for k in values if k not in EDITABLE_SETTINGS]
        if bad:
            raise ValueError(f"not editable: {', '.join(bad)}")
        with self.lock:
            cur = self.twin.config.settings.model_dump()
            cur.update(values)
            if cur["stow_wip_lower_min"] >= cur["stow_wip_upper_min"]:
                raise ValueError("lower Stow WIP threshold must be below the upper one")
            new = type(self.twin.config.settings)(**cur)
            self.twin.config.settings = new
            self.config.settings = new
            self._cache = None
        return new.model_dump()

    def work_item(self, item_id: str, verb: str) -> dict:
        with self.lock:
            wi = self.twin.work_items
            it = wi.complete(item_id) if verb == "complete" else wi.dismiss(item_id)
            if it is None:
                raise ValueError(f"no work item {item_id}")
            nid = (it.get("source_ref") or {}).get("notification")
            if nid:
                n = next((x for x in self.twin.notifications if x["id"] == nid), None)
                if n and not n["ack"]:
                    n["ack"], n["acked_at"] = True, clock(self.twin.now_minute)
            self._cache = None
        return it

    def packages(self, group: str, sub: str | None, column: str | None, by: str) -> dict:
        from app.simulation.station_ops.status import package_list

        with self.lock:
            rows = package_list(self.twin, group, sub, column, by, limit=50000)
        return {"count": len(rows), "items": rows}

    def report(self) -> dict:
        """The one-page shift report: outcomes, causes, decisions, tomorrow."""
        from app.runtime import explain

        replay = None
        with self.lock:
            if self.twin.done:
                cfg, ivs, n = explain.replay_inputs(self.twin)
                key = (n, len(ivs))
                cache = self.chat_context.get("replay")
                replay = cache[1] if cache and cache[0] == key else None
        if replay is None and self.twin.done:
            replay = explain.replay_without_decisions(cfg, ivs)
            self.chat_context["replay"] = (key, replay)
        with self.lock:
            snap = build_snapshot(self.twin, 0).model_dump(mode="json")
            views = build_views(self.twin, snap)
            dea = explain.dea(self.twin, self.loop, replay)
            otd = explain.otd(self.twin, self.loop, replay)
            co = self.twin.closeout
        return {
            "session": self.info(),
            "metrics": {
                k: snap["metrics"][k]
                for k in (
                    "dea",
                    "otd",
                    "timely_staged",
                    "stow_wip_compliance",
                    "induct_fph",
                    "lost_hours",
                    "induct_downtime_dpmo",
                    "sort_compliance",
                    "scan_compliance",
                )
            },
            "dea": dea.model_dump(),
            "otd": otd.model_dump(),
            "work_items": views["work_items_v2"]["summary"],
            "cycles": views["cycles"],
            "tomorrow": {
                "truckfile_version": co.truckfile_version,
                "plan_version": co.plan["version"] if co.plan else None,
                "totals": (co.plan or {}).get("labor_plan", {}).get("totals"),
                "opportunities": views["shift_plan_v2"]["opportunities"],
                "rotation": co.rotation_stats,
            },
            "simulated": True,
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
            "day": self.config.day,
            "truckfile_version": self.config.truckfile_version,
            "next_day_ready": self.twin.closeout.final_published_at is not None,
            "scale": self.config.scale,
            "pitch": self.config.name == "pitch_day",
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

    def ack(self, notification_id: int) -> dict | None:
        with self.lock:
            n = next((x for x in self.twin.notifications if x["id"] == notification_id), None)
            if n and not n["ack"]:
                n["ack"], n["acked_at"] = True, clock(self.twin.now_minute)
                self._cache = None
        return n

    def ack_all(self, audience: str = "all") -> int:
        k = 0
        with self.lock:
            for n in self.twin.notifications:
                if not n["ack"] and audience in ("all", n["audience"]):
                    n["ack"], n["acked_at"] = True, clock(self.twin.now_minute)
                    k += 1
            self._cache = None
        return k

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
        a.decided_by_person = True
        return a

    def dismiss(self, action_id: int) -> AgentAction:
        a = self.find_action(action_id)
        if a is None or a.status != "pending":
            raise ValueError(f"no pending recommendation #{action_id}")
        a.status = "dismissed"
        a.decided_by_person = True
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
        scale: float = 1.0,
    ) -> StationSession:
        if seed is None:
            # A fresh day every time — different arrivals, absences, drivers, friction.
            seed = random.SystemRandom().randrange(1, 100_000)
        cfg = config or build_preset(preset, seed, date.today(), scale=scale)
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
