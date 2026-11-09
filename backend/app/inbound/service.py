"""Truckfile generation and the daily ferry-status refresh."""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.inbound.ferry import FerryStatusProvider
from app.inbound.models import LinehaulTrip
from app.simulation.station_ops.config import LinehaulPlan
from app.simulation.station_ops.plan import generate_linehaul_plan


def _midnight(ofd_date: date) -> datetime:
    return datetime.combine(ofd_date, time(0, 0), tzinfo=UTC)


def get_truckfile(session: Session, ofd_date: date) -> list[LinehaulTrip]:
    return (
        session.query(LinehaulTrip)
        .filter(LinehaulTrip.ofd_date == ofd_date)
        .order_by(LinehaulTrip.planned_arrival)
        .all()
    )


def ensure_truckfile(session: Session, ofd_date: date, *, seed: int = 1) -> list[LinehaulTrip]:
    """Creates the day's synthetic truckfile if it doesn't exist yet
    (idempotent — the (ofd_date, trip_id) unique constraint backs this)."""
    existing = get_truckfile(session, ofd_date)
    if existing:
        return existing
    base = _midnight(ofd_date)
    for plan in generate_linehaul_plan(seed, ofd_date):
        session.add(
            LinehaulTrip(
                ofd_date=ofd_date,
                trip_id=plan.trip_id,
                origin=plan.origin,
                via_ferry=plan.via_ferry,
                ferry_sailing=plan.ferry_sailing,
                planned_arrival=base + timedelta(minutes=plan.planned_arrival_minute),
                volume=plan.volume,
                ferry_status="unknown" if plan.via_ferry else "not_applicable",
                ferry_checks=[],
            )
        )
    session.flush()
    return get_truckfile(session, ofd_date)


def refresh_ferry_status(
    session: Session, ofd_date: date, provider: FerryStatusProvider, *, now: datetime | None = None
) -> dict:
    """Checks every ferry-borne trip's sailing and writes the revised ETA
    back to the truckfile. Returns a summary of what changed."""
    now = now or datetime.now(UTC)
    trips = get_truckfile(session, ofd_date)
    changed = []
    for trip in trips:
        if not trip.via_ferry or not trip.ferry_sailing:
            continue
        st = provider.check(trip.ferry_sailing, ofd_date, now)
        previous = (trip.ferry_status, trip.delay_minutes)
        trip.ferry_status = st.status
        trip.delay_minutes = st.delay_minutes if st.status == "delayed" else 0
        trip.delay_reason = st.reason
        trip.revised_arrival = (
            None
            if st.status == "cancelled"
            else trip.planned_arrival + timedelta(minutes=trip.delay_minutes)
        )
        trip.last_checked_at = now
        trip.ferry_checks = [*(trip.ferry_checks or []), st.model_dump(mode="json")]
        if previous != (trip.ferry_status, trip.delay_minutes):
            changed.append(
                {
                    "trip_id": trip.trip_id,
                    "sailing": trip.ferry_sailing,
                    "from": list(previous),
                    "to": [trip.ferry_status, trip.delay_minutes],
                }
            )
    session.flush()
    ferry = [t for t in trips if t.via_ferry]
    return {
        "ofd_date": ofd_date.isoformat(),
        "provider": provider.name,
        "checked_at": now.isoformat(),
        "ferry_trips": len(ferry),
        "delayed": sum(1 for t in ferry if t.ferry_status == "delayed"),
        "cancelled": sum(1 for t in ferry if t.ferry_status == "cancelled"),
        "volume_at_risk": sum(
            t.volume for t in ferry if t.ferry_status in ("delayed", "cancelled")
        ),
        "changes": changed,
    }


def to_linehaul_plans(trips: list[LinehaulTrip]) -> list[LinehaulPlan]:
    """Truckfile rows -> plain twin inputs (the twin never reads Postgres)."""
    plans = []
    for t in trips:
        base = _midnight(t.ofd_date)
        plans.append(
            LinehaulPlan(
                trip_id=t.trip_id,
                origin=t.origin,
                planned_arrival_minute=(t.planned_arrival - base).total_seconds() / 60,
                delay_minutes=t.delay_minutes or 0,
                cancelled=t.ferry_status == "cancelled",
                volume=t.volume,
                via_ferry=t.via_ferry,
                ferry_sailing=t.ferry_sailing,
                delay_reason=t.delay_reason,
            )
        )
    return plans
