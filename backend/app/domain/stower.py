import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Stower(Base):
    """An anonymous, interchangeable stow-capacity resource — never a named
    individual (docs/SECURITY_AND_GOVERNANCE.md: synthetic data only, no
    real employee records).
    """

    __tablename__ = "stowers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
