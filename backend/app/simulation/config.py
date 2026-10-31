"""Typed scenario configuration, loaded from YAML
(docs/DIGITAL_TWIN_SPEC.md §"Configuration, not hardcoding" —
docs/OPEN_QUESTIONS.md's scenario-config-format question resolved as
YAML + a Pydantic model, not a bare dict, so a malformed scenario file
fails loudly at load time rather than mid-simulation).

Every capacity/timing/count a scenario can vary lives here, with
defaults matching docs/OPERATIONAL_DOMAIN_MODEL.md's synthetic
reference station — but nothing is hardcoded into the simulation model
itself (app/simulation/model.py never reads a literal count).
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class StationLayoutConfig(BaseModel):
    """Defaults match the full synthetic reference station
    (docs/OPERATIONAL_DOMAIN_MODEL.md §2: 54+68 aisles). The two
    Milestone 4 scenarios deliberately override these to a much smaller
    layout so hamper contention — the actual point of simulating
    capacity rather than assuming infinite throughput — shows up at a
    small, fast-to-run scale instead of being diluted across 122 aisles.
    """

    cluster_a_aisle_count: int = 54
    cluster_b_aisle_count: int = 68
    hamper_capacity: int = 40


class TruckArrivalConfig(BaseModel):
    truck_count: int
    first_arrival_offset_minutes: float = 0
    arrival_interval_minutes: float
    pallet_count_min: int = 4
    pallet_count_max: int = 10
    unload_duration_minutes: float = 10


class ParcelConfig(BaseModel):
    parcels_per_truck: int
    exception_rate: float = Field(0.05, ge=0, le=1)
    induct_duration_seconds: float = 3
    stow_duration_seconds: float = 20


class ResourceConfig(BaseModel):
    induct_capacity: int = 2
    stower_count: int = 10
    jackpot_clear_interval_minutes: float = 5


class ScenarioConfig(BaseModel):
    name: str
    description: str = ""
    seed: int
    station_layout: StationLayoutConfig = StationLayoutConfig()
    truck_arrivals: TruckArrivalConfig
    parcels: ParcelConfig
    resources: ResourceConfig = ResourceConfig()


def load_scenario(path: str | Path) -> ScenarioConfig:
    data = yaml.safe_load(Path(path).read_text())
    return ScenarioConfig.model_validate(data)


# backend/app/simulation/config.py -> repo root is three levels up.
SHIPPED_SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "simulation" / "scenarios"


class ShippedScenario(BaseModel):
    """One entry in the shipped-scenario allow-list (Milestone 10's
    API layer) — `filename` is the only thing an HTTP caller may use
    to select a scenario; it is never a free-form filesystem path, see
    `resolve_shipped_scenario_path`.
    """

    filename: str
    name: str
    description: str


def list_shipped_scenarios() -> list[ShippedScenario]:
    scenarios = []
    for path in sorted(SHIPPED_SCENARIOS_DIR.glob("*.yaml")):
        config = load_scenario(path)
        scenarios.append(
            ShippedScenario(filename=path.name, name=config.name, description=config.description)
        )
    return scenarios


def resolve_shipped_scenario_path(filename: str) -> Path:
    """Resolves a scenario *filename* (never a path) against the
    shipped-scenarios directory only — the API layer's one entry point
    for "run this scenario" must never accept an arbitrary filesystem
    path from an HTTP caller (unlike the CLI scripts, which are trusted
    local invocations). `Path.name` strips any directory component a
    caller tried to sneak in before the lookup, so this can only ever
    resolve to a file actually inside `SHIPPED_SCENARIOS_DIR`.
    """
    candidate = SHIPPED_SCENARIOS_DIR / Path(filename).name
    if not candidate.is_file():
        raise FileNotFoundError(f"no shipped scenario named {filename!r}")
    return candidate
