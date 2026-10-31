import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.enums import EventSourceKind
from app.events.event_types import PARCEL_SORT_ATTEMPTED
from app.events.schemas import EventEnvelope, UnknownEventTypeError, validate_payload


def _envelope(**overrides) -> EventEnvelope:
    defaults = dict(
        event_type=PARCEL_SORT_ATTEMPTED,
        entity_type="parcel",
        entity_id=uuid.uuid4(),
        correlation_id="SYN-TEST",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="test",
        source_kind=EventSourceKind.PHYSICAL_OBSERVATION,
        provenance="test:fixture",
        payload={"outcome": "sorted", "aisle_code": "A1"},
    )
    defaults.update(overrides)
    return EventEnvelope(**defaults)


def test_envelope_rejects_naive_occurred_at():
    with pytest.raises(ValidationError):
        _envelope(occurred_at=datetime(2026, 1, 1))  # no tzinfo


def test_resolved_idempotency_key_is_deterministic_without_explicit_key():
    entity_id = uuid.uuid4()
    occurred_at = datetime(2026, 1, 1, tzinfo=UTC)

    a = _envelope(entity_id=entity_id, occurred_at=occurred_at)
    b = _envelope(entity_id=entity_id, occurred_at=occurred_at)

    assert a.resolved_idempotency_key() == b.resolved_idempotency_key()


def test_resolved_idempotency_key_honors_explicit_override():
    envelope = _envelope(idempotency_key="custom-key-123")
    assert envelope.resolved_idempotency_key() == "custom-key-123"


def test_valid_sort_attempted_payload_passes():
    validate_payload(PARCEL_SORT_ATTEMPTED, 1, {"outcome": "sorted", "aisle_code": "B40"})


def test_sort_attempted_requires_aisle_code_when_sorted():
    with pytest.raises(ValidationError):
        validate_payload(PARCEL_SORT_ATTEMPTED, 1, {"outcome": "sorted"})


def test_jackpot_outcome_does_not_require_aisle_code():
    validate_payload(PARCEL_SORT_ATTEMPTED, 1, {"outcome": "jackpot"})


def test_unknown_event_type_is_rejected():
    with pytest.raises(UnknownEventTypeError):
        validate_payload("parcel.teleported", 1, {})


def test_unknown_schema_version_is_rejected():
    with pytest.raises(UnknownEventTypeError):
        validate_payload(PARCEL_SORT_ATTEMPTED, 99, {"outcome": "sorted", "aisle_code": "A1"})
