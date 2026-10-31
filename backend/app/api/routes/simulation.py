"""The digital-twin scenario runner view (Milestone 10). Runs a
shipped scenario synchronously and returns a summary — never the raw
event list (could be large; a future view that needs per-event detail
can add a dedicated endpoint deliberately, not by default here) — and
never writes to disk, unlike `scripts/run_simulation.py`'s own
Parquet export; an HTTP endpoint shouldn't have an uncontrolled
file-write side effect.
"""

from collections import Counter

from fastapi import APIRouter, HTTPException

from app.schemas.simulation import RunScenarioRequest, RunScenarioResponse
from app.simulation.config import (
    ShippedScenario,
    list_shipped_scenarios,
    load_scenario,
    resolve_shipped_scenario_path,
)
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
