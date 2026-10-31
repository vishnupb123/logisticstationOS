"""API-facing request/response models for the digital-twin scenario
runner (`backend/app/api/routes/simulation.py`). `RunScenarioRequest.scenario`
is a shipped-scenario filename, never a filesystem path — see
`app/simulation/config.py::resolve_shipped_scenario_path`.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RunScenarioRequest(BaseModel):
    scenario: str
    seed: int | None = None  # override the scenario file's own seed


class RunScenarioResponse(BaseModel):
    run_id: UUID
    scenario_name: str
    seed: int
    generated_at: datetime
    event_count: int
    event_type_counts: dict[str, int]
    # Always "simulated" — surfaced explicitly rather than implied, per
    # Milestone 10's exit criterion that every view states whether what
    # it shows is synthetic/simulated vs. live (ADR-0002/ADR-0006: a
    # simulation run is never presented as operational truth).
    source_kind: str = "simulated"
