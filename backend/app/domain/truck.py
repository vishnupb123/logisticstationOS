import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Truck(Base):
    """Inbound vehicle carrying pallets from an origin location
    (docs/OPERATIONAL_DOMAIN_MODEL.md §2). status/lifecycle_consistent are
    a *projection* rebuilt from the truck's event history
    (app/services/event_ingestion.py), not written to directly outside it.

    classification/status-like fields are plain strings rather than a
    Postgres ENUM type so adding a new value later doesn't require an
    ALTER TYPE migration — validated at the application layer via the
    StrEnum classes in app/domain/enums.py instead.
    """

    __tablename__ = "trucks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stations.id"), index=True)
    external_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    origin: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scheduled_arrival_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pallet_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    lifecycle_consistent: Mapped[bool] = mapped_column(default=True)
    lifecycle_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
