"""Truckfile persistence and ferry-status refresh (real Postgres)."""

from datetime import UTC, date, datetime

from app.inbound import service
from app.inbound.ferry import SyntheticFerryStatusProvider

_DAY = date(2026, 11, 20)


def test_ensure_truckfile_is_idempotent(db_session):
    first = service.ensure_truckfile(db_session, _DAY, seed=4)
    second = service.ensure_truckfile(db_session, _DAY, seed=4)
    assert [t.trip_id for t in first] == [t.trip_id for t in second]
    assert all(t.source_kind == "synthetic" for t in first)
    assert {t.ferry_status for t in first if not t.via_ferry} == {"not_applicable"}


def test_refresh_writes_revised_eta_and_keeps_history(db_session):
    service.ensure_truckfile(db_session, _DAY, seed=4)
    provider = SyntheticFerryStatusProvider(seed=4, force_weather="rough")
    t0 = datetime(2026, 11, 19, 22, 0, tzinfo=UTC)
    summary = service.refresh_ferry_status(db_session, _DAY, provider, now=t0)
    assert summary["ferry_trips"] > 0 and summary["delayed"] > 0
    trips = service.get_truckfile(db_session, _DAY)
    for t in trips:
        if t.via_ferry and t.ferry_status == "delayed":
            assert (t.revised_arrival - t.planned_arrival).total_seconds() == t.delay_minutes * 60
    service.refresh_ferry_status(db_session, _DAY, provider, now=t0)
    assert all(len(t.ferry_checks) == 2 for t in trips if t.via_ferry)


def test_provider_is_deterministic_and_severe_weather_cancels():
    p = SyntheticFerryStatusProvider(seed=1, force_weather="severe")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    a = [p.check(f"SAIL-{i}", _DAY, now) for i in range(60)]
    b = [p.check(f"SAIL-{i}", _DAY, now) for i in range(60)]
    assert a == b
    assert any(s.status == "cancelled" for s in a)
    assert all(s.delay_minutes >= 150 for s in a if s.status == "delayed")


def test_truckfile_round_trips_into_the_twin(db_session):
    from app.simulation.station_ops.plan import build_preset
    from app.simulation.station_ops.snapshot import run_station_day

    service.ensure_truckfile(db_session, _DAY, seed=4)
    service.refresh_ferry_status(
        db_session, _DAY, SyntheticFerryStatusProvider(seed=4, force_weather="severe")
    )
    plans = service.to_linehaul_plans(service.get_truckfile(db_session, _DAY))
    cfg = build_preset("normal_day")
    cfg.linehauls = plans
    snap = run_station_day(cfg)
    cancelled = sum(p.volume for p in plans if p.cancelled)
    assert snap.package_status["cancelled_inbound"] == cancelled
    assert snap.delivery["promised"] == sum(p.volume for p in plans)
