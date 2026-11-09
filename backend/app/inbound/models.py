"""The truckfile: one row per planned linehaul trip per OFD date.

Planning/reference data (synthetic, `source_kind="synthetic"`), not
operational events — so it is a plain table, not a stream in the events
table. The ferry columns are overwritten by each refresh (the latest
check wins), and `ferry_checks` keeps the per-refresh history so a delay's
evolution through the night stays auditable.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class LinehaulTrip(Base):
    __tablename__ = "linehaul_trips"
    __table_args__ = (UniqueConstraint("ofd_date", "trip_id", name="uq_linehaul_trip_per_day"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ofd_date: Mapped[date] = mapped_column(Date, index=True)
    trip_id: Mapped[str] = mapped_column(String(32))
    origin: Mapped[str] = mapped_column(String(32))
    via_ferry: Mapped[bool] = mapped_column(Boolean, default=False)
    ferry_sailing: Mapped[str | None] = mapped_column(String(32), nullable=True)
    planned_arrival: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    volume: Mapped[int] = mapped_column(Integer)
    cycle: Mapped[str] = mapped_column(String(32), default="CYCLE_1")

    ferry_status: Mapped[str] = mapped_column(String(16), default="not_applicable")
    delay_minutes: Mapped[int] = mapped_column(Integer, default=0)
    revised_arrival: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delay_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ferry_checks: Mapped[list] = mapped_column(JSONB, default=list)

    source_kind: Mapped[str] = mapped_column(String(16), default="synthetic")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
