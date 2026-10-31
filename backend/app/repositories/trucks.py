import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.truck import Truck


def get_by_id(session: Session, truck_id: uuid.UUID) -> Truck | None:
    return session.get(Truck, truck_id)


def get_by_external_code(session: Session, external_code: str) -> Truck | None:
    stmt = select(Truck).where(Truck.external_code == external_code)
    return session.scalars(stmt).first()
