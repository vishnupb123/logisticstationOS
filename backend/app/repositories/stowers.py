from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.stower import Stower


def get_or_create_by_code(session: Session, code: str) -> Stower:
    stmt = select(Stower).where(Stower.code == code)
    stower = session.scalars(stmt).first()
    if stower is not None:
        return stower
    stower = Stower(code=code)
    session.add(stower)
    session.flush()
    return stower
