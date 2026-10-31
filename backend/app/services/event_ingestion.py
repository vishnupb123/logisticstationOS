"""Cycle-1 event projection and ingestion.

Two halves, deliberately kept in one file because they're always used
together but matter for different reasons:

  - Pure projection (project_parcel/project_truck): no I/O, takes an
    ordered sequence of already-persisted events and derives current
    state. This is what makes "idempotent, out-of-order-safe projection"
    testable without a database — feed it the same events in any order,
    assert the same result.

  - DB-touching sync/ingest (sync_parcel_projection, sync_truck_projection,
    ingest_event): the single entry point real callers (the synthetic
    generator today; a future ingestion endpoint later) use to append an
    event and rebuild the affected entity's projection in one step.

Milestone 2 explicitly does not model the high-value/sideline/future-date/
exception cage workflows (docs/ENGINEERING_ROADMAP.md) — a parcel
classified as anything other than NORMAL_CYCLE1 simply stops at
PENDING_EXCEPTION; that's a scope boundary, not a bug.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.domain.enums import (
    ParcelClassification,
    ParcelLifecycleState,
    SortAttemptOutcome,
    TruckStatus,
)
from app.domain.parcel import Parcel
from app.domain.truck import Truck
from app.events.event_types import (
    PARCEL_CLASSIFIED,
    PARCEL_INDUCTED,
    PARCEL_JACKPOT_CLEARED,
    PARCEL_SORT_ATTEMPTED,
    PARCEL_STOWED,
    TRUCK_ARRIVED,
    TRUCK_UNLOADED,
)
from app.events.schemas import EventEnvelope, validate_payload
from app.events.store import AppendResult, EventStore
from app.repositories import aisles as aisle_repo
from app.repositories import bags as bag_repo

# --- Pure projection ----------------------------------------------------


@dataclass
class ParcelProjection:
    lifecycle_state: ParcelLifecycleState | None = None
    classification: ParcelClassification | None = None
    current_aisle_code: str | None = None
    bag_code: str | None = None
    stower_code: str | None = None
    consistent: bool = True
    notes: list[str] = field(default_factory=list)
    seen_inducted: bool = False


# event_type -> the lifecycle states it's valid to apply from. None means
# "must be the very first event seen for this parcel."
_PARCEL_VALID_PREDECESSORS: dict[str, set[ParcelLifecycleState] | None] = {
    PARCEL_INDUCTED: None,
    PARCEL_CLASSIFIED: {ParcelLifecycleState.INDUCTED},
    PARCEL_SORT_ATTEMPTED: {ParcelLifecycleState.CLASSIFIED},
    PARCEL_JACKPOT_CLEARED: {ParcelLifecycleState.JACKPOTTED},
    PARCEL_STOWED: {ParcelLifecycleState.SORTED},
}


def project_parcel(events) -> ParcelProjection:
    """events: any iterable of objects with .event_type/.occurred_at/.payload
    (an ORM Event row or a plain test double both work). Re-sorts by
    occurred_at itself (Python's sort is stable, so a caller that already
    ordered by (occurred_at, recorded_at) keeps that tiebreak) — out-of-
    order arrival must never change the projected result.
    """
    projection = ParcelProjection()
    for event in sorted(events, key=lambda e: e.occurred_at):
        _apply_parcel_event(projection, event)
    return projection


def _apply_parcel_event(projection: ParcelProjection, event) -> None:
    event_type = event.event_type
    payload = event.payload

    if event_type == PARCEL_INDUCTED:
        if projection.seen_inducted:
            projection.consistent = False
            projection.notes.append("duplicate parcel.inducted event received")
        projection.seen_inducted = True
        projection.lifecycle_state = ParcelLifecycleState.INDUCTED
        return

    if not projection.seen_inducted:
        projection.consistent = False
        projection.notes.append(f"{event_type} received before any parcel.inducted event")
        # Fall through — still apply the event's own information below
        # rather than discarding a real signal just because its
        # predecessor is missing.

    expected = _PARCEL_VALID_PREDECESSORS.get(event_type)
    if expected is not None and projection.lifecycle_state not in expected:
        projection.consistent = False
        projection.notes.append(
            f"{event_type} received while parcel in state {projection.lifecycle_state!s}, "
            f"expected one of {sorted(s.value for s in expected)}"
        )

    if event_type == PARCEL_CLASSIFIED:
        classification = ParcelClassification(payload["classification"])
        projection.classification = classification
        projection.lifecycle_state = (
            ParcelLifecycleState.CLASSIFIED
            if classification == ParcelClassification.NORMAL_CYCLE1
            else ParcelLifecycleState.PENDING_EXCEPTION
        )
        return

    if event_type == PARCEL_SORT_ATTEMPTED:
        if payload["outcome"] == SortAttemptOutcome.SORTED.value:
            projection.lifecycle_state = ParcelLifecycleState.SORTED
            projection.current_aisle_code = payload.get("aisle_code")
        else:
            projection.lifecycle_state = ParcelLifecycleState.JACKPOTTED
        return

    if event_type == PARCEL_JACKPOT_CLEARED:
        projection.lifecycle_state = ParcelLifecycleState.CLASSIFIED
        return

    if event_type == PARCEL_STOWED:
        projection.lifecycle_state = ParcelLifecycleState.STOWED
        projection.bag_code = payload.get("bag_code")
        projection.stower_code = payload.get("stower_code")
        return

    projection.consistent = False
    projection.notes.append(
        f"unknown event_type {event_type!r} encountered during parcel projection"
    )


@dataclass
class TruckProjection:
    status: TruckStatus | None = None
    consistent: bool = True
    notes: list[str] = field(default_factory=list)


def project_truck(events) -> TruckProjection:
    projection = TruckProjection()
    for event in sorted(events, key=lambda e: e.occurred_at):
        _apply_truck_event(projection, event)
    return projection


def _apply_truck_event(projection: TruckProjection, event) -> None:
    if event.event_type == TRUCK_ARRIVED:
        if projection.status is not None:
            projection.consistent = False
            projection.notes.append("duplicate truck.arrived event received")
        projection.status = TruckStatus.ARRIVED
        return

    if event.event_type == TRUCK_UNLOADED:
        if projection.status != TruckStatus.ARRIVED:
            projection.consistent = False
            projection.notes.append(
                f"truck.unloaded received while truck in state {projection.status!s}, "
                "expected arrived"
            )
        projection.status = TruckStatus.UNLOADED
        return

    projection.consistent = False
    projection.notes.append(
        f"unknown event_type {event.event_type!r} encountered during truck projection"
    )


# --- DB-touching sync and the public ingest_event entry point ----------


def sync_parcel_projection(
    session: Session,
    parcel_id: uuid.UUID,
    *,
    truck_id: uuid.UUID | None = None,
    tracking_id: str | None = None,
    sal_label: str | None = None,
    origin: str | None = None,
) -> Parcel:
    """Rebuilds parcel_id's row from its full event history. truck_id/
    tracking_id are only used if the Parcel row doesn't exist yet (i.e.
    this is being called for a parcel.inducted event) — ignored otherwise.
    """
    events = EventStore(session).list_for_entity("parcel", parcel_id)
    projection = project_parcel(events)

    parcel = session.get(Parcel, parcel_id)
    if parcel is None:
        if truck_id is None or tracking_id is None:
            raise ValueError(
                f"no parcel row for id={parcel_id} and no truck_id/tracking_id given to create one "
                "— was this the parcel's first parcel.inducted event?"
            )
        parcel = Parcel(
            id=parcel_id,
            truck_id=truck_id,
            tracking_id=tracking_id,
            sal_label=sal_label,
            origin=origin,
            lifecycle_state=ParcelLifecycleState.INDUCTED.value,
        )
        session.add(parcel)
        session.flush()

    if projection.lifecycle_state is not None:
        parcel.lifecycle_state = projection.lifecycle_state.value
    parcel.classification = projection.classification.value if projection.classification else None
    parcel.lifecycle_consistent = projection.consistent
    parcel.lifecycle_notes = "; ".join(projection.notes) or None

    if projection.current_aisle_code:
        aisle = aisle_repo.get_by_code(session, projection.current_aisle_code)
        parcel.current_aisle_id = aisle.id if aisle else None

    if projection.bag_code:
        bag = bag_repo.get_or_create_by_code(
            session, projection.bag_code, stower_code=projection.stower_code
        )
        parcel.bag_id = bag.id

    session.flush()
    return parcel


def sync_truck_projection(
    session: Session,
    truck_id: uuid.UUID,
    *,
    station_id: uuid.UUID | None = None,
    external_code: str | None = None,
    origin: str | None = None,
    scheduled_arrival_at=None,
    pallet_count: int | None = None,
) -> Truck:
    events = EventStore(session).list_for_entity("truck", truck_id)
    projection = project_truck(events)

    truck = session.get(Truck, truck_id)
    if truck is None:
        if station_id is None or external_code is None:
            raise ValueError(
                f"no truck row for id={truck_id} and no station_id/external_code given to "
                "create one — was this the truck's first truck.arrived event?"
            )
        truck = Truck(
            id=truck_id,
            station_id=station_id,
            external_code=external_code,
            origin=origin,
            scheduled_arrival_at=scheduled_arrival_at,
            pallet_count=pallet_count,
            status=TruckStatus.SCHEDULED.value,
        )
        session.add(truck)
        session.flush()

    if projection.status is not None:
        truck.status = projection.status.value
    truck.lifecycle_consistent = projection.consistent
    truck.lifecycle_notes = "; ".join(projection.notes) or None
    session.flush()
    return truck


def ingest_event(
    session: Session, envelope: EventEnvelope, *, station_id: uuid.UUID | None = None
) -> AppendResult:
    """The single entry point for getting an event into StationOS:
    append to the log, then rebuild the affected entity's projection.
    Idempotent end to end — appending the same envelope twice is a no-op
    duplicate at the store layer, and resyncing from an unchanged event
    log recomputes the same projected state.

    station_id is only consulted when this is a truck.arrived event for a
    truck StationOS hasn't seen before (needed to create the Truck row);
    ignored in every other case.
    """
    validated_payload = validate_payload(
        envelope.event_type, envelope.schema_version, envelope.payload
    )
    result = EventStore(session).append(envelope)

    if envelope.entity_type == "truck":
        extra: dict = {}
        if envelope.event_type == TRUCK_ARRIVED:
            extra = {
                "station_id": station_id,
                "external_code": envelope.correlation_id,
                "origin": validated_payload.origin,
                "scheduled_arrival_at": validated_payload.scheduled_arrival_at,
                "pallet_count": validated_payload.pallet_count,
            }
        sync_truck_projection(session, envelope.entity_id, **extra)
    else:
        extra = {}
        if envelope.event_type == PARCEL_INDUCTED:
            extra = {
                "truck_id": validated_payload.truck_id,
                "tracking_id": validated_payload.tracking_id,
                "sal_label": validated_payload.sal_label,
                "origin": validated_payload.origin,
            }
        sync_parcel_projection(session, envelope.entity_id, **extra)

    return result
