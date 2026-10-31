"""Typed event envelope and per-event-type payload schemas
(docs/DATA_ARCHITECTURE.md §"Event schema conventions").

A producer builds an EventEnvelope and hands it to
app.events.store.EventStore.append(). recorded_at is deliberately not a
field here — only the store, at persist time, gets to say when StationOS
actually recorded something; a producer claiming its own recorded_at would
defeat the whole point of distinguishing occurred_at from recorded_at.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import EventSourceKind, ParcelClassification, SortAttemptOutcome
from app.events.event_types import (
    PARCEL_CLASSIFIED,
    PARCEL_INDUCTED,
    PARCEL_JACKPOT_CLEARED,
    PARCEL_SORT_ATTEMPTED,
    PARCEL_STOWED,
    TRUCK_ARRIVED,
    TRUCK_UNLOADED,
)


class EventEnvelope(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str
    entity_type: Literal["truck", "parcel"]
    entity_id: uuid.UUID
    correlation_id: str
    occurred_at: datetime
    source: str
    source_kind: EventSourceKind
    provenance: str
    schema_version: int = 1
    idempotency_key: str | None = None
    payload: dict

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value

    def resolved_idempotency_key(self) -> str:
        """A caller may supply its own idempotency_key (e.g. a producer's
        own dedupe token); otherwise this envelope's own identifying
        fields form a deterministic one — so the *same logical event*
        submitted twice collides, without requiring every producer to
        invent its own key.
        """
        if self.idempotency_key:
            return self.idempotency_key
        return f"{self.event_type}:{self.entity_id}:{self.occurred_at.isoformat()}"


# --- Per-event-type payload schemas, Cycle 1 only ----------------------


class TruckArrivedPayload(BaseModel):
    origin: str
    scheduled_arrival_at: datetime | None = None
    pallet_count: int


class TruckUnloadedPayload(BaseModel):
    pallet_count_unloaded: int


class ParcelInductedPayload(BaseModel):
    truck_id: uuid.UUID
    tracking_id: str
    origin: str | None = None
    sal_label: str | None = None


class ParcelClassifiedPayload(BaseModel):
    classification: ParcelClassification


class ParcelSortAttemptedPayload(BaseModel):
    outcome: SortAttemptOutcome
    aisle_code: str | None = None

    @model_validator(mode="after")
    def _aisle_code_required_when_sorted(self) -> "ParcelSortAttemptedPayload":
        # A field_validator on aisle_code alone would not run at all when
        # the field is omitted and falls back to its default (Pydantic
        # only validates a default with validate_default=True) — this is
        # a cross-field rule, so a model-level validator is both more
        # correct and clearer about what it's actually checking.
        if self.outcome == SortAttemptOutcome.SORTED and not self.aisle_code:
            raise ValueError("aisle_code is required when outcome is 'sorted'")
        return self


class ParcelJackpotClearedPayload(BaseModel):
    note: str | None = None


class ParcelStowedPayload(BaseModel):
    bag_code: str
    stower_code: str


EVENT_PAYLOAD_SCHEMAS: dict[tuple[str, int], type[BaseModel]] = {
    (TRUCK_ARRIVED, 1): TruckArrivedPayload,
    (TRUCK_UNLOADED, 1): TruckUnloadedPayload,
    (PARCEL_INDUCTED, 1): ParcelInductedPayload,
    (PARCEL_CLASSIFIED, 1): ParcelClassifiedPayload,
    (PARCEL_SORT_ATTEMPTED, 1): ParcelSortAttemptedPayload,
    (PARCEL_JACKPOT_CLEARED, 1): ParcelJackpotClearedPayload,
    (PARCEL_STOWED, 1): ParcelStowedPayload,
}


class UnknownEventTypeError(ValueError):
    pass


def validate_payload(event_type: str, schema_version: int, payload: dict) -> BaseModel:
    """Raises (pydantic.ValidationError or UnknownEventTypeError) rather
    than returning None on failure — an invalid payload is a producer bug
    to reject outright, not real-world data worth preserving as-is (unlike
    an out-of-sequence-but-well-formed event, which the projector accepts
    and merely flags — see app/services/event_ingestion.py).
    """
    schema = EVENT_PAYLOAD_SCHEMAS.get((event_type, schema_version))
    if schema is None:
        raise UnknownEventTypeError(
            f"no payload schema registered for event_type={event_type!r} "
            f"schema_version={schema_version!r}"
        )
    return schema.model_validate(payload)
