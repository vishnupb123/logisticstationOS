"""DB-dependent tests for EventStore — these need a real PostgreSQL
connection (skipped automatically if one isn't reachable; see
tests/conftest.py::_schema). Deliberately not mocked: the behavior under
test is the database's own unique-constraint enforcement, which a mock
would just assume works.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domain.enums import EventSourceKind
from app.events.event_types import PARCEL_SORT_ATTEMPTED
from app.events.schemas import EventEnvelope
from app.events.store import EventStore


def _envelope(entity_id: uuid.UUID, occurred_at: datetime, **overrides) -> EventEnvelope:
    defaults = dict(
        event_type=PARCEL_SORT_ATTEMPTED,
        entity_type="parcel",
        entity_id=entity_id,
        correlation_id="SYN-TEST",
        occurred_at=occurred_at,
        source="test",
        source_kind=EventSourceKind.PHYSICAL_OBSERVATION,
        provenance="test:fixture",
        payload={"outcome": "sorted", "aisle_code": "A1"},
    )
    defaults.update(overrides)
    return EventEnvelope(**defaults)


def test_append_persists_and_is_readable(db_session):
    entity_id = uuid.uuid4()
    occurred_at = datetime(2026, 1, 1, tzinfo=UTC)
    store = EventStore(db_session)

    result = store.append(_envelope(entity_id, occurred_at))

    assert result.status == "appended"
    events = store.list_for_entity("parcel", entity_id)
    assert len(events) == 1
    assert events[0].event_id == result.event_id


def test_appending_the_same_event_twice_is_a_no_op_duplicate(db_session):
    entity_id = uuid.uuid4()
    occurred_at = datetime(2026, 1, 1, tzinfo=UTC)
    store = EventStore(db_session)
    envelope = _envelope(entity_id, occurred_at)

    first = store.append(envelope)
    second = store.append(envelope)

    assert first.status == "appended"
    assert second.status == "duplicate"
    assert second.event_id == first.event_id
    assert len(store.list_for_entity("parcel", entity_id)) == 1


def test_appending_two_distinct_events_with_the_same_idempotency_key_dedupes(db_session):
    """Two envelopes with different event_ids but the same explicit
    idempotency_key are still the same logical event — the second append
    must be treated as a duplicate of the first, not a second row.
    """
    entity_id = uuid.uuid4()
    occurred_at = datetime(2026, 1, 1, tzinfo=UTC)
    store = EventStore(db_session)

    first = store.append(_envelope(entity_id, occurred_at, idempotency_key="shared-key"))
    second = store.append(
        _envelope(
            entity_id,
            occurred_at + timedelta(seconds=1),
            idempotency_key="shared-key",
            event_id=uuid.uuid4(),
        )
    )

    assert first.status == "appended"
    assert second.status == "duplicate"
    assert len(store.list_for_entity("parcel", entity_id)) == 1


def test_list_for_entity_orders_by_occurred_at_regardless_of_insertion_order(db_session):
    entity_id = uuid.uuid4()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    store = EventStore(db_session)

    # Insert the "later" event first, deliberately out of order.
    later = _envelope(entity_id, base + timedelta(minutes=5), idempotency_key="later")
    earlier = _envelope(entity_id, base, idempotency_key="earlier")
    store.append(later)
    store.append(earlier)

    events = store.list_for_entity("parcel", entity_id)
    assert [e.idempotency_key for e in events] == ["earlier", "later"]


def test_invalid_payload_is_rejected_and_nothing_is_persisted(db_session):
    entity_id = uuid.uuid4()
    occurred_at = datetime(2026, 1, 1, tzinfo=UTC)
    store = EventStore(db_session)

    # missing aisle_code
    bad_envelope = _envelope(entity_id, occurred_at, payload={"outcome": "sorted"})

    with pytest.raises(ValidationError):
        store.append(bad_envelope)

    assert store.list_for_entity("parcel", entity_id) == []
