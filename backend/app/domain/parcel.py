import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Parcel(Base):
    """An individually tracked parcel (docs/OPERATIONAL_DOMAIN_MODEL.md §2).

    classification/lifecycle_state/current_aisle_id/bag_id are a
    *projection* rebuilt from this parcel's event history
    (app/services/event_ingestion.py::sync_parcel_projection) — never
    written to directly. lifecycle_consistent/lifecycle_notes record when
    that projection found the event history didn't match the expected
    state machine (docs/OPERATIONAL_DOMAIN_MODEL.md's own caution: don't
    assume virtual state matches physical state).
    """

    __tablename__ = "parcels"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    truck_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("trucks.id"), index=True)
    tracking_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    sal_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(128), nullable=True)
    classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lifecycle_state: Mapped[str] = mapped_column(String(32))
    current_aisle_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("aisles.id"), nullable=True
    )
    bag_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("bags.id"), nullable=True)
    lifecycle_consistent: Mapped[bool] = mapped_column(default=True)
    lifecycle_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
