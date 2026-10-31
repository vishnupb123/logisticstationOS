import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Bag(Base):
    """Container of stowed parcels — the unit carried into Pick & Stage
    (docs/OPERATIONAL_DOMAIN_MODEL.md §2). Created on first reference by a
    parcel.stowed event (app/repositories/bags.py::get_or_create_by_code).
    """

    __tablename__ = "bags"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    stower_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stowers.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
