"""Frame iterator for the live Station Operations view: steps the twin in
small sim-time increments, runs the agent loop on a fixed cadence, and
yields one JSON-ready frame per step until every route has departed.
"""

from collections.abc import Callable, Iterator

from sqlalchemy.orm import Session

from app.agents.station_ops.loop import Mode, StationOpsAgentLoop
from app.simulation.station_ops.config import StationOpsConfig
from app.simulation.station_ops.model import StationOpsTwin
from app.simulation.station_ops.snapshot import build_snapshot

MAX_FRAMES = 1000
START_MINUTE = 60  # 01:00 — nothing happens in the station before the first linehaul


def iter_frames(
    config: StationOpsConfig,
    *,
    step_minutes: float,
    mode: Mode,
    agent_every_minutes: float = 15,
    session_factory: Callable[[], Session] | None = None,
) -> Iterator[dict]:
    if step_minutes <= 0:
        raise ValueError("step_minutes must be positive")
    twin = StationOpsTwin(config)
    loop = StationOpsAgentLoop(mode, session_factory)
    twin.run_until(START_MINUTE)
    next_agent = START_MINUTE
    for frame in range(1, MAX_FRAMES + 1):
        snap = build_snapshot(twin, frame)
        new_actions = []
        if twin.now_minute >= next_agent and not twin.done:
            new_actions = loop.step(twin, snap)
            next_agent = twin.now_minute + agent_every_minutes
            if any(a.applied for a in new_actions):
                snap = build_snapshot(twin, frame)  # show the lever's effect immediately
        yield {
            "snapshot": snap.model_dump(mode="json"),
            "agent": {
                "mode": mode,
                "risks": [r.model_dump(mode="json") for r in loop.current_risks],
                "new_actions": [a.model_dump(mode="json") for a in new_actions],
                "actions_total": len(loop.actions),
            },
        }
        if twin.done:
            return
        twin.run_until(twin.now_minute + step_minutes)
