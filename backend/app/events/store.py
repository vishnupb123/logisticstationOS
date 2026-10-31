import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.events.models import Event
from app.events.schemas import EventEnvelope, validate_payload


@dataclass(frozen=True)
class AppendResult:
    status: Literal["appended", "duplicate"]
    event_id: uuid.UUID


class EventStore:
    """Append-only access to the events table (ADR-0004). Never updates or
    deletes a row. A duplicate idempotency_key is the one thing it
    silently tolerates (INSERT ... ON CONFLICT DO NOTHING, enforced by a
    real unique constraint — not just application-level discipline);
    everything else (an invalid payload) is a hard error.
    """

    def __init__(self, session: Session):
        self._session = session

    def append(self, envelope: EventEnvelope) -> AppendResult:
        validate_payload(envelope.event_type, envelope.schema_version, envelope.payload)

        idempotency_key = envelope.resolved_idempotency_key()
        stmt = (
            pg_insert(Event)
            .values(
                event_id=envelope.event_id,
                event_type=envelope.event_type,
                entity_type=envelope.entity_type,
                entity_id=envelope.entity_id,
                correlation_id=envelope.correlation_id,
                occurred_at=envelope.occurred_at,
                source=envelope.source,
                source_kind=envelope.source_kind.value,
                provenance=envelope.provenance,
                idempotency_key=idempotency_key,
                schema_version=envelope.schema_version,
                payload=envelope.payload,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(Event.event_id)
        )
        row = self._session.execute(stmt).first()
        if row is not None:
            return AppendResult(status="appended", event_id=row.event_id)

        existing_id = self._session.scalar(
            select(Event.event_id).where(Event.idempotency_key == idempotency_key)
        )
        return AppendResult(status="duplicate", event_id=existing_id)

    def list_for_entity(self, entity_type: str, entity_id: uuid.UUID) -> list[Event]:
        """Ordered by (occurred_at, recorded_at) — domain time first,
        ingestion time as the tiebreak — so a caller folding these into a
        projection sees them in the order they actually happened, not the
        order they arrived.
        """
        stmt = (
            select(Event)
            .where(Event.entity_type == entity_type, Event.entity_id == entity_id)
            .order_by(Event.occurred_at.asc(), Event.recorded_at.asc())
        )
        return list(self._session.scalars(stmt))
