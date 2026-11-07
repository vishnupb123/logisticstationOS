"""Typed, read-only query functions onto the Milestone 3 analytics
DuckDB file (`backend/analytics/`'s dbt project output) — the Python-
side query interface `docs/SYSTEM_ARCHITECTURE.md` said this module
would get "once an API/agent consumer needs it." The Flow Intelligence
Agent (Milestone 5) is that consumer.

Each function returns a typed Pydantic model, never a raw DataFrame or
tuple — this is what makes these usable as agent tools with "validated
inputs/outputs, not raw database... access"
(docs/AGENTIC_ARCHITECTURE.md). Connections are read-only: nothing in
this module can write to the analytical database.

Assumes the dbt project has already been run (`dbt run` against
`backend/analytics/`) — if the underlying tables don't exist, DuckDB
raises its own CatalogException, left to propagate rather than
swallowed, since "no analytics pipeline has run yet" is a real
condition an agent's evidence-gathering should fail loudly on, not
paper over with an empty-looking default.
"""

from contextlib import closing
from datetime import datetime

import duckdb
from pydantic import BaseModel


class JackpotVolumeReading(BaseModel):
    cumulative_diverts: int
    cumulative_clears: int
    currently_in_jackpot: int


class WipsReading(BaseModel):
    wip_count: int


class InductThroughputBucket(BaseModel):
    hour_bucket: datetime
    parcels_inducted: int


class StowThroughputBucket(BaseModel):
    hour_bucket: datetime
    stower_code: str | None
    parcels_stowed: int


class ParcelDwellTimeStats(BaseModel):
    parcel_count: int
    min_dwell_seconds: float | None
    max_dwell_seconds: float | None
    avg_dwell_seconds: float | None


def _connect(duckdb_path: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(duckdb_path, read_only=True)


def get_jackpot_volume(duckdb_path: str) -> JackpotVolumeReading:
    with closing(_connect(duckdb_path)) as con:
        row = con.sql(
            "SELECT cumulative_diverts, cumulative_clears, currently_in_jackpot "
            "FROM metric_jackpot_volume"
        ).fetchone()
    if row is None:
        return JackpotVolumeReading(
            cumulative_diverts=0, cumulative_clears=0, currently_in_jackpot=0
        )
    return JackpotVolumeReading(
        cumulative_diverts=row[0], cumulative_clears=row[1], currently_in_jackpot=row[2]
    )


def get_wips(duckdb_path: str) -> WipsReading:
    with closing(_connect(duckdb_path)) as con:
        row = con.sql("SELECT wip_count FROM metric_wips").fetchone()
    return WipsReading(wip_count=row[0] if row else 0)


def get_induct_throughput(duckdb_path: str) -> list[InductThroughputBucket]:
    with closing(_connect(duckdb_path)) as con:
        rows = con.sql(
            "SELECT hour_bucket, parcels_inducted FROM metric_induct_throughput "
            "ORDER BY hour_bucket"
        ).fetchall()
    return [InductThroughputBucket(hour_bucket=r[0], parcels_inducted=r[1]) for r in rows]


def get_stow_throughput(duckdb_path: str) -> list[StowThroughputBucket]:
    with closing(_connect(duckdb_path)) as con:
        rows = con.sql(
            "SELECT hour_bucket, stower_code, parcels_stowed "
            "FROM metric_stow_throughput ORDER BY hour_bucket, stower_code"
        ).fetchall()
    return [
        StowThroughputBucket(hour_bucket=r[0], stower_code=r[1], parcels_stowed=r[2]) for r in rows
    ]


def get_parcel_dwell_time_stats(duckdb_path: str) -> ParcelDwellTimeStats:
    with closing(_connect(duckdb_path)) as con:
        row = con.sql(
            "SELECT count(*), min(dwell_seconds), max(dwell_seconds), avg(dwell_seconds) "
            "FROM metric_parcel_dwell_time"
        ).fetchone()
    return ParcelDwellTimeStats(
        parcel_count=row[0],
        min_dwell_seconds=row[1],
        max_dwell_seconds=row[2],
        avg_dwell_seconds=row[3],
    )


class StageDuration(BaseModel):
    count: int
    avg_seconds: float | None
    p50_seconds: float | None
    p90_seconds: float | None


class EndToEndStats(BaseModel):
    """The Cycle-1 funnel and per-stage cycle times, from
    `curated_parcel_lifecycle` (one row per parcel). Status: proposed —
    same caveat as the other Milestone 3 metrics; the stage boundaries
    are the event types' own, not a validated operational definition.
    """

    parcels_inducted: int
    parcels_exception: int
    parcels_sorted: int
    parcels_ever_jackpotted: int
    parcels_stowed: int
    induct_to_sort: StageDuration
    sort_to_stow: StageDuration
    induct_to_stow: StageDuration


_DURATION_SQL = "count({e}), avg({e}), quantile_cont({e}, 0.5), quantile_cont({e}, 0.9)"


def get_end_to_end_stats(duckdb_path: str) -> EndToEndStats:
    i2s = "date_diff('second', inducted_at, sorted_at)"
    s2s = "date_diff('second', sorted_at, stowed_at)"
    i2t = "date_diff('second', inducted_at, stowed_at)"
    with closing(_connect(duckdb_path)) as con:
        row = con.sql(
            "SELECT "
            "count(inducted_at), "
            "count(*) FILTER (WHERE classification IS NOT NULL "
            "AND classification <> 'normal_cycle1'), "
            "count(sorted_at), count(first_jackpot_diverted_at), count(stowed_at), "
            f"{_DURATION_SQL.format(e=i2s)}, {_DURATION_SQL.format(e=s2s)}, "
            f"{_DURATION_SQL.format(e=i2t)} "
            "FROM curated_parcel_lifecycle"
        ).fetchone()
    assert row is not None  # an aggregate without GROUP BY always returns one row

    def stage(offset: int) -> StageDuration:
        count, avg, p50, p90 = row[offset : offset + 4]
        return StageDuration(count=count, avg_seconds=avg, p50_seconds=p50, p90_seconds=p90)

    return EndToEndStats(
        parcels_inducted=row[0],
        parcels_exception=row[1],
        parcels_sorted=row[2],
        parcels_ever_jackpotted=row[3],
        parcels_stowed=row[4],
        induct_to_sort=stage(5),
        sort_to_stow=stage(9),
        induct_to_stow=stage(13),
    )
