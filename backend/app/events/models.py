import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Event(Base):
    """The event log of record (ADR-0004): append-only, never updated or
    deleted. Current-entity-state tables under app/domain are projections
    derived from this log (app/services/event_ingestion.py), not the other
    way around.

    entity_id/entity_type are intentionally not a real foreign key: a
    single events table spans multiple aggregate types (truck, parcel),
    so there's no single column it could reference. That's a deliberate
    trade — enforced correctness here would mean one events table per
    aggregate type, which ADR-0004 rejected in favor of one log.
    """

    __tablename__ = "events"

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    source: Mapped[str] = mapped_column(String(128))
    source_kind: Mapped[str] = mapped_column(String(32))
    provenance: Mapped[str] = mapped_column(String(256))
    idempotency_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSONB)
