import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.parcel import Parcel


def get_by_id(session: Session, parcel_id: uuid.UUID) -> Parcel | None:
    return session.get(Parcel, parcel_id)


def get_by_tracking_id(session: Session, tracking_id: str) -> Parcel | None:
    stmt = select(Parcel).where(Parcel.tracking_id == tracking_id)
    return session.scalars(stmt).first()
