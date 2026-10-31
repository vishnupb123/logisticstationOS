from datetime import UTC, datetime

import pytest

from app.analytics import duckdb_queries
from tests.helpers.duckdb_fixtures import build_metrics_duckdb


def test_get_jackpot_volume(tmp_path):
    path = tmp_path / "metrics.duckdb"
    build_metrics_duckdb(path, cumulative_diverts=10, cumulative_clears=7)

    reading = duckdb_queries.get_jackpot_volume(str(path))

    assert reading.cumulative_diverts == 10
    assert reading.cumulative_clears == 7
    assert reading.currently_in_jackpot == 3


def test_get_wips(tmp_path):
    path = tmp_path / "metrics.duckdb"
    build_metrics_duckdb(path, wip_count=4)

    reading = duckdb_queries.get_wips(str(path))

    assert reading.wip_count == 4


def test_get_induct_throughput(tmp_path):
    path = tmp_path / "metrics.duckdb"
    rows = [
        (datetime(2026, 1, 1, 2, tzinfo=UTC), 10),
        (datetime(2026, 1, 1, 3, tzinfo=UTC), 15),
    ]
    build_metrics_duckdb(path, induct_rows=rows)

    buckets = duckdb_queries.get_induct_throughput(str(path))

    assert len(buckets) == 2
    assert buckets[0].parcels_inducted == 10
    assert buckets[1].parcels_inducted == 15
    assert buckets[0].hour_bucket < buckets[1].hour_bucket


def test_get_stow_throughput(tmp_path):
    path = tmp_path / "metrics.duckdb"
    rows = [
        (datetime(2026, 1, 1, 2, tzinfo=UTC), "STOWER-01", 5),
        (datetime(2026, 1, 1, 2, tzinfo=UTC), "STOWER-02", 3),
    ]
    build_metrics_duckdb(path, stow_rows=rows)

    buckets = duckdb_queries.get_stow_throughput(str(path))

    assert len(buckets) == 2
    assert {b.stower_code for b in buckets} == {"STOWER-01", "STOWER-02"}


def test_get_parcel_dwell_time_stats(tmp_path):
    path = tmp_path / "metrics.duckdb"
    base = datetime(2026, 1, 1, 2, tzinfo=UTC)
    rows = [
        ("P1", base, base.replace(minute=10)),
        ("P2", base, base.replace(minute=30)),
    ]
    build_metrics_duckdb(path, dwell_rows=rows)

    stats = duckdb_queries.get_parcel_dwell_time_stats(str(path))

    assert stats.parcel_count == 2
    assert stats.min_dwell_seconds == 600
    assert stats.max_dwell_seconds == 1800
    assert stats.avg_dwell_seconds == 1200


def test_parcel_dwell_time_stats_with_no_rows(tmp_path):
    path = tmp_path / "metrics.duckdb"
    build_metrics_duckdb(path, dwell_rows=[])

    stats = duckdb_queries.get_parcel_dwell_time_stats(str(path))

    assert stats.parcel_count == 0
    assert stats.min_dwell_seconds is None


def test_missing_table_raises_rather_than_returning_a_silent_default(tmp_path):
    """No analytics pipeline run yet is a real condition evidence-
    gathering should fail loudly on, not paper over.
    """
    import duckdb as duckdb_module

    path = tmp_path / "empty.duckdb"
    con = duckdb_module.connect(str(path))
    con.close()

    with pytest.raises(Exception):  # noqa: B017 — DuckDB's own CatalogException
        duckdb_queries.get_jackpot_volume(str(path))
