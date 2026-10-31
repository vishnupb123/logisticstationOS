from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.bag import Bag
from app.repositories import stowers as stower_repo


def get_or_create_by_code(session: Session, code: str, *, stower_code: str | None = None) -> Bag:
    stmt = select(Bag).where(Bag.code == code)
    bag = session.scalars(stmt).first()
    if bag is not None:
        return bag

    stower_id = None
    if stower_code:
        stower_id = stower_repo.get_or_create_by_code(session, stower_code).id

    bag = Bag(code=code, stower_id=stower_id)
    session.add(bag)
    session.flush()
    return bag
