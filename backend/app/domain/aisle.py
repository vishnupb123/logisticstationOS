import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Aisle(Base):
    """One aisle in a sort cluster; has exactly one hamper and one scanner
    (docs/OPERATIONAL_DOMAIN_MODEL.md §2). Reference data, seeded once via
    app/services/seed.py — not projected from events.
    """

    __tablename__ = "aisles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    station_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stations.id"), index=True)
    cluster: Mapped[str] = mapped_column(String(8))
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Hamper(Base):
    """1:1 with its aisle. Capacity is a scenario/config parameter
    (docs/DIGITAL_TWIN_SPEC.md), not a universal constant.
    """

    __tablename__ = "hampers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    aisle_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("aisles.id"), unique=True, index=True
    )
    capacity: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
