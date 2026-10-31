"""Read-only HTTP endpoints onto the Milestone 3 analytics DuckDB file
(`app/analytics/duckdb_queries.py`) — the "induct and sortation" /
"stow and jackpot" views (Milestone 10). Always reads the server-
configured DuckDB path (`app/db/duckdb.py::resolve_duckdb_path`),
never a caller-supplied path (see `app/schemas/agents.py` for why).

If the dbt pipeline has never been run, the underlying tables don't
exist — `duckdb_queries` lets DuckDB's own error propagate rather than
returning a silently-empty default (docs/AGENTIC_ARCHITECTURE.md's
"fail loudly" precedent); this layer turns that into a clean 503 so a
frontend can render "analytics not built yet" instead of a raw 500.
"""

from collections.abc import Callable

import duckdb
from fastapi import APIRouter, HTTPException

from app.analytics import duckdb_queries
from app.db.duckdb import resolve_duckdb_path

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _run_or_503[T](query: Callable[[str], T]) -> T:
    try:
        return query(str(resolve_duckdb_path()))
    except duckdb.Error as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "analytics not available — the dbt pipeline hasn't been run yet "
                f"against this DuckDB file ({exc})"
            ),
        ) from exc


@router.get("/jackpot-volume", response_model=duckdb_queries.JackpotVolumeReading)
def jackpot_volume() -> duckdb_queries.JackpotVolumeReading:
    return _run_or_503(duckdb_queries.get_jackpot_volume)


@router.get("/wips", response_model=duckdb_queries.WipsReading)
def wips() -> duckdb_queries.WipsReading:
    return _run_or_503(duckdb_queries.get_wips)


@router.get("/induct-throughput", response_model=list[duckdb_queries.InductThroughputBucket])
def induct_throughput() -> list[duckdb_queries.InductThroughputBucket]:
    return _run_or_503(duckdb_queries.get_induct_throughput)


@router.get("/stow-throughput", response_model=list[duckdb_queries.StowThroughputBucket])
def stow_throughput() -> list[duckdb_queries.StowThroughputBucket]:
    return _run_or_503(duckdb_queries.get_stow_throughput)


@router.get("/parcel-dwell-time", response_model=duckdb_queries.ParcelDwellTimeStats)
def parcel_dwell_time() -> duckdb_queries.ParcelDwellTimeStats:
    return _run_or_503(duckdb_queries.get_parcel_dwell_time_stats)
