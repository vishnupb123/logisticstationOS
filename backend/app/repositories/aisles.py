import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.aisle import Aisle


def get_by_code(session: Session, code: str) -> Aisle | None:
    stmt = select(Aisle).where(Aisle.code == code)
    return session.scalars(stmt).first()


def get_by_id(session: Session, aisle_id: uuid.UUID) -> Aisle | None:
    return session.get(Aisle, aisle_id)
