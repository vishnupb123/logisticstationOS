"""Pure tests for the synthetic Cycle-1 event generator: determinism,
payload validity, and a conservation check (every generated parcel ends
in a defined terminal/pending state — none vanish) via the real projector.
"""

from app.domain.enums import ParcelLifecycleState
from app.events.schemas import validate_payload
from app.services.event_ingestion import project_parcel
from app.services.synthetic_events import SyntheticScenario, generate_cycle1_events

_TERMINAL_STATES = {ParcelLifecycleState.STOWED, ParcelLifecycleState.PENDING_EXCEPTION}


def test_same_seed_produces_identical_output():
    scenario = SyntheticScenario(seed=7, truck_count=3, parcels_per_truck=5)

    first = generate_cycle1_events(scenario)
    second = generate_cycle1_events(scenario)

    assert [e.model_dump(mode="json") for e in first] == [e.model_dump(mode="json") for e in second]


def test_different_seeds_produce_different_output():
    a = generate_cycle1_events(SyntheticScenario(seed=1, truck_count=3, parcels_per_truck=5))
    b = generate_cycle1_events(SyntheticScenario(seed=2, truck_count=3, parcels_per_truck=5))

    assert [e.model_dump(mode="json") for e in a] != [e.model_dump(mode="json") for e in b]


def test_every_generated_event_payload_is_valid():
    events = generate_cycle1_events(SyntheticScenario(seed=42, truck_count=4, parcels_per_truck=10))
    assert len(events) > 0

    for event in events:
        # Raises on failure — the test fails loudly rather than silently
        # passing on an uninspected result.
        validate_payload(event.event_type, event.schema_version, event.payload)


def test_no_parcel_vanishes_from_the_generated_stream():
    """Conservation check: every parcel the generator inducts must end up
    in a defined terminal/pending state once its events are projected —
    none left dangling mid-pipeline with no further events explaining why.
    """
    scenario = SyntheticScenario(seed=99, truck_count=5, parcels_per_truck=15)
    events = generate_cycle1_events(scenario)

    by_parcel: dict = {}
    for event in events:
        if event.entity_type == "parcel":
            by_parcel.setdefault(event.entity_id, []).append(event)

    expected_parcel_count = scenario.truck_count * scenario.parcels_per_truck
    assert len(by_parcel) == expected_parcel_count

    inconsistent = []
    non_terminal = []
    for parcel_id, parcel_events in by_parcel.items():
        projection = project_parcel(parcel_events)
        if not projection.consistent:
            inconsistent.append((parcel_id, projection.notes))
        if projection.lifecycle_state not in _TERMINAL_STATES:
            non_terminal.append((parcel_id, projection.lifecycle_state))

    assert inconsistent == [], f"generator produced an inconsistent event sequence: {inconsistent}"
    assert non_terminal == [], f"generator left parcels in a non-terminal state: {non_terminal}"


def test_jackpot_and_exception_rates_are_respected_approximately():
    """Not a precise statistical test — just confirms the knobs actually
    do something, at a scale large enough that 0% or 100% would be an
    obvious bug, not noise.
    """
    scenario = SyntheticScenario(
        seed=5, truck_count=10, parcels_per_truck=50, jackpot_rate=0.2, exception_rate=0.1
    )
    events = generate_cycle1_events(scenario)

    classified = [e for e in events if e.event_type == "parcel.classified"]
    jackpotted = [e for e in events if e.event_type == "parcel.jackpot_cleared"]

    exception_count = sum(1 for e in classified if e.payload["classification"] != "normal_cycle1")
    total = len(classified)

    assert 0 < exception_count < total
    assert 0 < len(jackpotted) < total
