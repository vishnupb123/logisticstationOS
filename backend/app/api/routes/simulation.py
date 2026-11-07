"""The digital-twin scenario runner view (Milestone 10). Runs a
shipped scenario synchronously and returns a summary — never the raw
event list (could be large; a future view that needs per-event detail
can add a dedicated endpoint deliberately, not by default here) — and
never writes to disk, unlike `scripts/run_simulation.py`'s own
Parquet export; an HTTP endpoint shouldn't have an uncontrolled
file-write side effect.
"""

import time
from collections import Counter
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.schemas.simulation import RunScenarioRequest, RunScenarioResponse
from app.simulation.config import (
    ShippedScenario,
    list_shipped_scenarios,
    load_scenario,
    resolve_shipped_scenario_path,
)
from app.simulation.live import LiveSnapshot, iter_live_snapshots
from app.simulation.model import run_scenario

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.get("/scenarios", response_model=list[ShippedScenario])
def scenarios() -> list[ShippedScenario]:
    return list_shipped_scenarios()


@router.post("/run", response_model=RunScenarioResponse)
def run(request: RunScenarioRequest) -> RunScenarioResponse:
    try:
        path = resolve_shipped_scenario_path(request.scenario)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    config = load_scenario(path)
    if request.seed is not None:
        config = config.model_copy(update={"seed": request.seed})

    result = run_scenario(config)
    event_type_counts = Counter(e.event_type for e in result.events)

    return RunScenarioResponse(
        run_id=result.run_id,
        scenario_name=result.scenario_name,
        seed=result.seed,
        generated_at=result.generated_at,
        event_count=len(result.events),
        event_type_counts=dict(event_type_counts),
    )


@router.get("/live", response_class=StreamingResponse)
def live(
    scenario: str,
    seed: int | None = None,
    step_seconds: float = Query(30, ge=5, le=600, description="Simulated seconds per frame"),
    frame_interval_ms: int = Query(
        200, ge=0, le=2000, description="Wall-clock pacing between frames (0 = as fast as possible)"
    ),
) -> StreamingResponse:
    """Server-Sent Events stream of `LiveSnapshot` frames — the twin
    played back step by step so a UI can watch it progress. Same
    allow-list scenario resolution as `/run`; nothing persisted.
    Parameters are bounded, and the stream itself is capped at
    `app.simulation.live.MAX_FRAMES` frames, so it always terminates.
    """
    try:
        path = resolve_shipped_scenario_path(scenario)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    config = load_scenario(path)
    if seed is not None:
        config = config.model_copy(update={"seed": seed})

    def frames() -> Iterator[str]:
        for snapshot in iter_live_snapshots(config, step_seconds=step_seconds):
            yield f"event: snapshot\ndata: {snapshot.model_dump_json()}\n\n"
            if frame_interval_ms and not snapshot.done:
                time.sleep(frame_interval_ms / 1000)
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Re-exported so the OpenAPI schema / API reference can name the frame type.
__all__ = ["LiveSnapshot", "router"]
