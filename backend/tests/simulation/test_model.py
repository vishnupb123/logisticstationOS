"""Core digital-twin tests. No database involved — run_scenario is pure
(no I/O), so these exercise it directly, the same way Milestone 2's
synthetic-generator tests do.
"""

from collections import Counter
from pathlib import Path

from app.domain.enums import ParcelLifecycleState
from app.events.schemas import validate_payload
from app.services.event_ingestion import project_parcel
from app.simulation.config import ScenarioConfig, load_scenario
from app.simulation.model import run_scenario

_SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "simulation" / "scenarios"
_TERMINAL_STATES = {ParcelLifecycleState.STOWED, ParcelLifecycleState.PENDING_EXCEPTION}


def _small_config(**overrides) -> ScenarioConfig:
    base = {
        "name": "test",
        "seed": 42,
        "station_layout": {
            "cluster_a_aisle_count": 2,
            "cluster_b_aisle_count": 2,
            "hamper_capacity": 2,
        },
        "truck_arrivals": {"truck_count": 2, "arrival_interval_minutes": 5},
        "parcels": {"parcels_per_truck": 10},
        "resources": {
            "induct_capacity": 1,
            "stower_count": 1,
            "jackpot_clear_interval_minutes": 1,
        },
    }
    base.update(overrides)
    return ScenarioConfig.model_validate(base)


def _by_parcel(events):
    grouped: dict = {}
    for event in events:
        if event.entity_type == "parcel":
            grouped.setdefault(event.entity_id, []).append(event)
    return grouped


def test_same_seed_produces_identical_output():
    config = _small_config()
    first = run_scenario(config)
    second = run_scenario(config)

    assert [e.model_dump(mode="json") for e in first.events] == [
        e.model_dump(mode="json") for e in second.events
    ]


def test_different_seeds_produce_different_output():
    a = run_scenario(_small_config(seed=1))
    b = run_scenario(_small_config(seed=2))

    a_dump = [e.model_dump(mode="json") for e in a.events]
    b_dump = [e.model_dump(mode="json") for e in b.events]
    assert a_dump != b_dump


def test_every_generated_event_payload_is_valid():
    result = run_scenario(_small_config())
    assert len(result.events) > 0
    for event in result.events:
        validate_payload(event.event_type, event.schema_version, event.payload)


def test_no_parcel_vanishes_from_the_simulated_run():
    """Conservation check (docs/ENGINEERING_ROADMAP.md Milestone 4 exit
    criteria): every parcel the twin creates must end up in a defined
    terminal state, verified via the real projector
    (app.services.event_ingestion.project_parcel) — the same function
    that governs Postgres-backed projections — not a twin-specific
    reimplementation of the check.
    """
    config = _small_config(truck_arrivals={"truck_count": 3, "arrival_interval_minutes": 5})
    result = run_scenario(config)

    by_parcel = _by_parcel(result.events)
    expected_parcel_count = config.truck_arrivals.truck_count * config.parcels.parcels_per_truck
    assert len(by_parcel) == expected_parcel_count

    inconsistent = []
    non_terminal = []
    for parcel_id, events in by_parcel.items():
        projection = project_parcel(events)
        if not projection.consistent:
            inconsistent.append((parcel_id, projection.notes))
        if projection.lifecycle_state not in _TERMINAL_STATES:
            non_terminal.append((parcel_id, projection.lifecycle_state))

    assert inconsistent == [], f"twin produced an inconsistent event sequence: {inconsistent}"
    assert non_terminal == [], f"twin left parcels in a non-terminal state: {non_terminal}"


def test_truck_and_parcel_counts_match_config():
    config = _small_config(truck_arrivals={"truck_count": 4, "arrival_interval_minutes": 5})
    result = run_scenario(config)

    truck_arrived = [e for e in result.events if e.event_type == "truck.arrived"]
    assert len(truck_arrived) == config.truck_arrivals.truck_count

    inducted = [e for e in result.events if e.event_type == "parcel.inducted"]
    assert len(inducted) == config.truck_arrivals.truck_count * config.parcels.parcels_per_truck


def test_full_hampers_actually_produce_jackpot_diversions():
    """The point of simulating finite hamper capacity rather than a
    probability knob (unlike Milestone 2's generator): with only 2
    aisles, capacity 1 each, and 20 parcels, contention is forced, not
    merely possible.
    """
    config = _small_config(
        station_layout={
            "cluster_a_aisle_count": 2,
            "cluster_b_aisle_count": 0,
            "hamper_capacity": 1,
        },
        truck_arrivals={"truck_count": 1, "arrival_interval_minutes": 5},
        parcels={"parcels_per_truck": 20, "exception_rate": 0.0},
    )
    result = run_scenario(config)

    jackpot_attempts = [
        e
        for e in result.events
        if e.event_type == "parcel.sort_attempted" and e.payload["outcome"] == "jackpot"
    ]
    assert len(jackpot_attempts) > 0

    jackpot_cleared = [e for e in result.events if e.event_type == "parcel.jackpot_cleared"]
    assert len(jackpot_cleared) == len(jackpot_attempts)


def test_shipped_scenarios_run_reproducibly_and_conserve_parcels():
    for filename in ("normal_operations.yaml", "delayed_inbound_trucks.yaml"):
        config = load_scenario(_SCENARIOS_DIR / filename)
        first = run_scenario(config)
        second = run_scenario(config)

        assert [e.model_dump(mode="json") for e in first.events] == [
            e.model_dump(mode="json") for e in second.events
        ]

        by_parcel = _by_parcel(first.events)
        for parcel_id, events in by_parcel.items():
            projection = project_parcel(events)
            assert projection.consistent, (
                f"{filename}: parcel {parcel_id} inconsistent: {projection.notes}"
            )
            assert projection.lifecycle_state in _TERMINAL_STATES, (
                f"{filename}: parcel {parcel_id} ended in {projection.lifecycle_state}"
            )


def test_delayed_scenario_actually_differs_from_normal_operations():
    """The two required scenarios (docs/ENGINEERING_ROADMAP.md Milestone
    4) must be meaningfully distinct, not copies with a different seed —
    checked here via each truck's actual arrival time, which the
    scenario's whole point is to shift.
    """
    normal = run_scenario(load_scenario(_SCENARIOS_DIR / "normal_operations.yaml"))
    delayed = run_scenario(load_scenario(_SCENARIOS_DIR / "delayed_inbound_trucks.yaml"))

    normal_arrivals = sorted(
        e.occurred_at for e in normal.events if e.event_type == "truck.arrived"
    )
    delayed_arrivals = sorted(
        e.occurred_at for e in delayed.events if e.event_type == "truck.arrived"
    )

    assert delayed_arrivals[0] > normal_arrivals[0]
    normal_span = normal_arrivals[-1] - normal_arrivals[0]
    delayed_span = delayed_arrivals[-1] - delayed_arrivals[0]
    assert delayed_span < normal_span


def test_run_metadata_is_present():
    config = _small_config()
    result = run_scenario(config)

    assert result.scenario_name == config.name
    assert result.seed == config.seed
    assert result.simpy_version
    assert result.run_id is not None
    assert result.generated_at is not None


def test_event_type_counts_are_internally_consistent():
    """sort_attempted(outcome=sorted) count + jackpot occurrences should
    equal total sort_attempted; jackpot occurrences should equal
    jackpot_cleared count (every diversion in a closed run gets cleared).
    """
    config = _small_config(truck_arrivals={"truck_count": 3, "arrival_interval_minutes": 5})
    result = run_scenario(config)
    counts = Counter(e.event_type for e in result.events)

    sort_outcomes = Counter(
        e.payload["outcome"] for e in result.events if e.event_type == "parcel.sort_attempted"
    )
    total_sort_attempted = sort_outcomes["sorted"] + sort_outcomes.get("jackpot", 0)
    assert total_sort_attempted == counts["parcel.sort_attempted"]
    assert sort_outcomes.get("jackpot", 0) == counts.get("parcel.jackpot_cleared", 0)
    assert sort_outcomes["sorted"] == counts["parcel.stowed"]
