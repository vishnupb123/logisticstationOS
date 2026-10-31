"""DB-dependent end-to-end tests for ingest_event: append + projection
sync against a real PostgreSQL connection (skipped if unreachable — see
tests/conftest.py::_schema). This is the exit-criteria test for
Milestone 2: a synthetic truck-arrival-through-stow event stream can be
ingested, persisted, and read back idempotently.
"""

import uuid

import pytest

from app.domain.enums import ParcelLifecycleState, TruckStatus
from app.domain.parcel import Parcel
from app.domain.truck import Truck
from app.events.event_types import TRUCK_ARRIVED
from app.repositories import aisles as aisle_repo
from app.services.event_ingestion import ingest_event, sync_parcel_projection
from app.services.seed import seed_aisles, seed_station
from app.services.synthetic_events import SyntheticScenario, generate_cycle1_events


def test_full_cycle1_stream_ingests_idempotently_and_projects_correctly(db_session):
    """Scopes every query to the entity ids this test itself generated,
    rather than assuming the tables start empty — the events/trucks/
    parcels tables are shared with other tests (and, in local dev, with
    whatever a developer has manually seeded via the CLI script; see
    docs/OPEN_QUESTIONS.md), so "assert exactly N rows in the table" is
    the wrong assertion even though "assert exactly N rows *this test
    created*" is exactly as strong a check.
    """
    station = seed_station(db_session)
    seed_aisles(db_session, station)
    db_session.flush()

    scenario = SyntheticScenario(seed=123, truck_count=2, parcels_per_truck=8)
    events = generate_cycle1_events(scenario)
    truck_ids = {e.entity_id for e in events if e.entity_type == "truck"}
    parcel_ids = {e.entity_id for e in events if e.entity_type == "parcel"}

    appended_first_pass = 0
    for envelope in events:
        station_id = station.id if envelope.event_type == TRUCK_ARRIVED else None
        result = ingest_event(db_session, envelope, station_id=station_id)
        assert result.status == "appended"
        appended_first_pass += 1

    assert appended_first_pass == len(events)

    # Every truck ends up unloaded, every parcel ends up stowed or
    # pending-exception — the Milestone 2 exit criteria, checked against
    # the actual persisted rows, not just the pure projector.
    trucks = db_session.query(Truck).filter(Truck.id.in_(truck_ids)).all()
    assert len(trucks) == scenario.truck_count
    for truck in trucks:
        assert truck.status == TruckStatus.UNLOADED.value
        assert truck.lifecycle_consistent is True

    parcels = db_session.query(Parcel).filter(Parcel.id.in_(parcel_ids)).all()
    assert len(parcels) == scenario.truck_count * scenario.parcels_per_truck
    for parcel in parcels:
        assert parcel.lifecycle_state in {
            ParcelLifecycleState.STOWED.value,
            ParcelLifecycleState.PENDING_EXCEPTION.value,
        }
        assert parcel.lifecycle_consistent is True
        if parcel.lifecycle_state == ParcelLifecycleState.STOWED.value:
            assert parcel.bag_id is not None

    # Re-ingesting the exact same stream (replay) must be a true no-op:
    # every event reports as a duplicate, and every row's projected state
    # is byte-for-byte the same as before.
    before = {p.id: (p.lifecycle_state, p.bag_id, p.current_aisle_id) for p in parcels}

    for envelope in events:
        station_id = station.id if envelope.event_type == TRUCK_ARRIVED else None
        result = ingest_event(db_session, envelope, station_id=station_id)
        assert result.status == "duplicate"

    db_session.expire_all()
    after = {
        p.id: (p.lifecycle_state, p.bag_id, p.current_aisle_id)
        for p in db_session.query(Parcel).filter(Parcel.id.in_(parcel_ids)).all()
    }
    assert before == after


def test_sorted_parcel_resolves_to_a_real_aisle_row(db_session):
    station = seed_station(db_session)
    seed_aisles(db_session, station)
    db_session.flush()

    scenario = SyntheticScenario(seed=5, truck_count=1, parcels_per_truck=20)
    events = generate_cycle1_events(scenario)
    parcel_ids = {e.entity_id for e in events if e.entity_type == "parcel"}

    for envelope in events:
        station_id = station.id if envelope.event_type == TRUCK_ARRIVED else None
        ingest_event(db_session, envelope, station_id=station_id)

    stowed = (
        db_session.query(Parcel)
        .filter(Parcel.id.in_(parcel_ids))
        .filter(Parcel.lifecycle_state == ParcelLifecycleState.STOWED.value)
        .all()
    )
    assert len(stowed) > 0
    for parcel in stowed:
        assert parcel.current_aisle_id is not None
        aisle = aisle_repo.get_by_id(db_session, parcel.current_aisle_id)
        assert aisle is not None
        assert aisle.code.startswith(("A", "B"))


def test_sync_parcel_projection_refuses_to_guess_at_a_missing_parcel(db_session):
    """If a parcel row doesn't exist yet and the caller doesn't supply
    enough to create one (truck_id/tracking_id), sync_parcel_projection
    must raise rather than silently doing nothing or inventing a row —
    this is the guard that keeps a non-inducted event from ever creating
    a parcel.
    """
    with pytest.raises(ValueError, match="no parcel row"):
        sync_parcel_projection(db_session, uuid.uuid4())
