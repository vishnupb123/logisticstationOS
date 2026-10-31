import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Station(Base):
    """A single fictional reference station (see docs/OPERATIONAL_DOMAIN_MODEL.md).
    Multi-station support isn't needed yet, so this stays minimal (code,
    name) rather than speculatively designed for a future that isn't here.
    """

    __tablename__ = "stations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
