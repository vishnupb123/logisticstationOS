"""Pure-logic tests for app.services.event_ingestion's projection functions.

No database involved — these construct event-like objects directly and
feed them to project_parcel/project_truck, which is exactly the point:
idempotent, out-of-order-safe projection should be verifiable without
touching Postgres at all.
"""

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.domain.enums import ParcelLifecycleState, TruckStatus
from app.events.event_types import (
    PARCEL_CLASSIFIED,
    PARCEL_INDUCTED,
    PARCEL_JACKPOT_CLEARED,
    PARCEL_SORT_ATTEMPTED,
    PARCEL_STOWED,
    TRUCK_ARRIVED,
    TRUCK_UNLOADED,
)
from app.services.event_ingestion import project_parcel, project_truck


@dataclass
class FakeEvent:
    event_type: str
    occurred_at: datetime
    payload: dict = field(default_factory=dict)


def _t(offset_seconds: int) -> datetime:
    return datetime(2026, 1, 1, 2, 30, tzinfo=UTC) + timedelta(seconds=offset_seconds)


def _happy_path_events() -> list[FakeEvent]:
    """A parcel that jackpots once, clears, gets sorted, then stowed."""
    return [
        FakeEvent(PARCEL_INDUCTED, _t(0), {}),
        FakeEvent(PARCEL_CLASSIFIED, _t(1), {"classification": "normal_cycle1"}),
        FakeEvent(PARCEL_SORT_ATTEMPTED, _t(2), {"outcome": "jackpot"}),
        FakeEvent(PARCEL_JACKPOT_CLEARED, _t(3), {}),
        FakeEvent(PARCEL_SORT_ATTEMPTED, _t(4), {"outcome": "sorted", "aisle_code": "A12"}),
        FakeEvent(PARCEL_STOWED, _t(5), {"bag_code": "BAG-A12-001", "stower_code": "STOWER-03"}),
    ]


def test_happy_path_ends_stowed_with_correct_fields():
    projection = project_parcel(_happy_path_events())

    assert projection.lifecycle_state == ParcelLifecycleState.STOWED
    assert projection.current_aisle_code == "A12"
    assert projection.bag_code == "BAG-A12-001"
    assert projection.stower_code == "STOWER-03"
    assert projection.consistent is True
    assert projection.notes == []


def test_projection_is_order_independent():
    """The whole point of out-of-order handling: shuffling the same event
    set must never change the final projected state.
    """
    events = _happy_path_events()
    baseline = project_parcel(events)

    rng = random.Random(1234)
    for _ in range(10):
        shuffled = events[:]
        rng.shuffle(shuffled)
        shuffled_projection = project_parcel(shuffled)

        assert shuffled_projection.lifecycle_state == baseline.lifecycle_state
        assert shuffled_projection.current_aisle_code == baseline.current_aisle_code
        assert shuffled_projection.bag_code == baseline.bag_code
        assert shuffled_projection.consistent == baseline.consistent


def test_replaying_the_same_events_twice_is_idempotent():
    events = _happy_path_events()
    once = project_parcel(events)
    twice = project_parcel(events + events)  # duplicates, as if replayed

    assert once.lifecycle_state == twice.lifecycle_state
    assert once.current_aisle_code == twice.current_aisle_code
    assert once.bag_code == twice.bag_code
    # Duplicates are still flagged, even though the final state is correct.
    assert twice.consistent is False


def test_non_normal_classification_stops_at_pending_exception():
    events = [
        FakeEvent(PARCEL_INDUCTED, _t(0), {}),
        FakeEvent(PARCEL_CLASSIFIED, _t(1), {"classification": "high_value"}),
    ]
    projection = project_parcel(events)

    assert projection.lifecycle_state == ParcelLifecycleState.PENDING_EXCEPTION
    assert projection.consistent is True


def test_missing_induct_event_is_flagged_but_still_projected():
    events = [
        FakeEvent(PARCEL_CLASSIFIED, _t(1), {"classification": "normal_cycle1"}),
        FakeEvent(PARCEL_SORT_ATTEMPTED, _t(2), {"outcome": "sorted", "aisle_code": "B40"}),
    ]
    projection = project_parcel(events)

    assert projection.consistent is False
    assert any("before any parcel.inducted event" in note for note in projection.notes)
    # Still projects the best available current state from what it has.
    assert projection.lifecycle_state == ParcelLifecycleState.SORTED
    assert projection.current_aisle_code == "B40"


def test_stow_without_prior_sort_is_flagged_but_still_applied():
    events = [
        FakeEvent(PARCEL_INDUCTED, _t(0), {}),
        FakeEvent(PARCEL_CLASSIFIED, _t(1), {"classification": "normal_cycle1"}),
        FakeEvent(PARCEL_STOWED, _t(2), {"bag_code": "BAG-X", "stower_code": "STOWER-01"}),
    ]
    projection = project_parcel(events)

    assert projection.consistent is False
    assert any("expected one of ['sorted']" in note for note in projection.notes)
    assert projection.lifecycle_state == ParcelLifecycleState.STOWED


def test_conflicting_sort_events_flagged_latest_wins():
    events = [
        FakeEvent(PARCEL_INDUCTED, _t(0), {}),
        FakeEvent(PARCEL_CLASSIFIED, _t(1), {"classification": "normal_cycle1"}),
        FakeEvent(PARCEL_SORT_ATTEMPTED, _t(2), {"outcome": "sorted", "aisle_code": "A1"}),
        FakeEvent(PARCEL_SORT_ATTEMPTED, _t(3), {"outcome": "sorted", "aisle_code": "A2"}),
    ]
    projection = project_parcel(events)

    # Second sort_attempted arrives while already SORTED, not CLASSIFIED —
    # flagged as inconsistent, but the latest signal (A2) is still trusted.
    assert projection.consistent is False
    assert projection.current_aisle_code == "A2"


def test_unknown_event_type_is_flagged():
    events = [
        FakeEvent(PARCEL_INDUCTED, _t(0), {}),
        FakeEvent("parcel.teleported", _t(1), {}),
    ]
    projection = project_parcel(events)

    assert projection.consistent is False
    assert any("unknown event_type" in note for note in projection.notes)


def test_truck_happy_path():
    events = [
        FakeEvent(TRUCK_ARRIVED, _t(0), {}),
        FakeEvent(TRUCK_UNLOADED, _t(1), {}),
    ]
    projection = project_truck(events)

    assert projection.status == TruckStatus.UNLOADED
    assert projection.consistent is True


def test_truck_unloaded_before_arrived_is_flagged():
    events = [FakeEvent(TRUCK_UNLOADED, _t(0), {})]
    projection = project_truck(events)

    assert projection.consistent is False
    assert projection.status == TruckStatus.UNLOADED
