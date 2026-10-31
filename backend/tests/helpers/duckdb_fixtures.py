"""Builds a minimal DuckDB file with the same table shapes the real dbt
project (backend/analytics/) produces, without running dbt — these
tests are about app/analytics/duckdb_queries.py's SQL, not about
re-verifying the dbt pipeline (already covered in Milestone 3/4's test
suites and manual verification). Keeps this test suite fast and
dbt-dependency-free.
"""

from datetime import UTC, datetime
from pathlib import Path

import duckdb


def build_metrics_duckdb(
    path: Path,
    *,
    cumulative_diverts: int = 0,
    cumulative_clears: int = 0,
    wip_count: int = 0,
    dwell_rows: list[tuple[str, datetime, datetime]] | None = None,
    induct_rows: list[tuple[datetime, int]] | None = None,
    stow_rows: list[tuple[datetime, str, int]] | None = None,
) -> None:
    dwell_rows = dwell_rows if dwell_rows is not None else []
    induct_rows = (
        induct_rows if induct_rows is not None else [(datetime(2026, 1, 1, 2, tzinfo=UTC), 10)]
    )
    stow_rows = (
        stow_rows
        if stow_rows is not None
        else [(datetime(2026, 1, 1, 2, tzinfo=UTC), "STOWER-01", 5)]
    )

    con = duckdb.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE metric_jackpot_volume AS SELECT "
            "? AS cumulative_diverts, ? AS cumulative_clears, ? AS currently_in_jackpot",
            [cumulative_diverts, cumulative_clears, cumulative_diverts - cumulative_clears],
        )
        con.execute("CREATE TABLE metric_wips AS SELECT ? AS wip_count", [wip_count])

        con.execute(
            "CREATE TABLE metric_induct_throughput "
            "(hour_bucket TIMESTAMPTZ, parcels_inducted INTEGER)"
        )
        if induct_rows:
            con.executemany("INSERT INTO metric_induct_throughput VALUES (?, ?)", induct_rows)

        con.execute(
            "CREATE TABLE metric_stow_throughput "
            "(hour_bucket TIMESTAMPTZ, stower_code VARCHAR, parcels_stowed INTEGER)"
        )
        if stow_rows:
            con.executemany("INSERT INTO metric_stow_throughput VALUES (?, ?, ?)", stow_rows)

        con.execute(
            "CREATE TABLE metric_parcel_dwell_time "
            "(parcel_id VARCHAR, inducted_at TIMESTAMPTZ, stowed_at TIMESTAMPTZ, "
            "dwell_seconds BIGINT)"
        )
        rows_with_dwell = [
            (parcel_id, inducted_at, stowed_at, int((stowed_at - inducted_at).total_seconds()))
            for parcel_id, inducted_at, stowed_at in dwell_rows
        ]
        if rows_with_dwell:
            con.executemany(
                "INSERT INTO metric_parcel_dwell_time VALUES (?, ?, ?, ?)", rows_with_dwell
            )
    finally:
        con.close()
