"""Idempotent reference-data seeding — the one station, its aisles, and
their hampers. Not projected from events (nothing "happens" to create an
aisle); seeded once and read thereafter. Safe to call repeatedly: each
function only inserts what's missing.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.aisle import Aisle, Hamper
from app.domain.enums import SortCluster
from app.domain.station import Station
from app.repositories import aisles as aisle_repo

DEFAULT_STATION_CODE = "NOVA-1"
DEFAULT_STATION_NAME = "Station NOVA-1"
DEFAULT_CLUSTER_A_AISLE_COUNT = 54
DEFAULT_CLUSTER_B_AISLE_COUNT = 68
DEFAULT_HAMPER_CAPACITY = 40


def seed_station(
    session: Session, *, code: str = DEFAULT_STATION_CODE, name: str = DEFAULT_STATION_NAME
) -> Station:
    station = session.scalars(select(Station).where(Station.code == code)).first()
    if station is not None:
        return station
    station = Station(code=code, name=name)
    session.add(station)
    session.flush()
    return station


def seed_aisles(
    session: Session,
    station: Station,
    *,
    cluster_a_count: int = DEFAULT_CLUSTER_A_AISLE_COUNT,
    cluster_b_count: int = DEFAULT_CLUSTER_B_AISLE_COUNT,
    hamper_capacity: int = DEFAULT_HAMPER_CAPACITY,
) -> None:
    """Counts are the synthetic reference defaults from
    docs/OPERATIONAL_DOMAIN_MODEL.md §2 — configuration, not a fact about
    any real station.
    """
    for cluster, count in ((SortCluster.A, cluster_a_count), (SortCluster.B, cluster_b_count)):
        for n in range(1, count + 1):
            code = f"{cluster.value}{n}"
            if aisle_repo.get_by_code(session, code) is not None:
                continue
            aisle = Aisle(station_id=station.id, cluster=cluster.value, code=code)
            session.add(aisle)
            session.flush()
            session.add(Hamper(aisle_id=aisle.id, capacity=hamper_capacity))
    session.flush()
