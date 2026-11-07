from collections.abc import Generator
from contextlib import closing, contextmanager
from pathlib import Path

import duckdb

from app.core.config import get_settings

settings = get_settings()

# backend/app/db/duckdb.py -> repo root is three levels up.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def resolve_duckdb_path() -> Path:
    configured = Path(settings.duckdb_path)
    if configured.is_absolute():
        path = configured
    else:
        path = (_REPO_ROOT / "backend" / configured).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def get_duckdb_connection() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Open a DuckDB connection to the local analytical database file.

    DuckDB is embedded (single-process, file-backed) — this is a thin
    connection manager, not a pool. Analytical services open a short-lived
    connection per query/batch rather than holding one open indefinitely.
    """
    conn = duckdb.connect(str(resolve_duckdb_path()))
    try:
        yield conn
    finally:
        conn.close()


def check_connection() -> bool:
    """Best-effort connectivity probe used by the readiness endpoint.

    Opens read-only when the file exists: DuckDB refuses a second
    in-process connection to the same file with a *different*
    configuration, so a read-write probe racing the analytics routes'
    read-only connections (app/analytics/duckdb_queries.py) reported
    "unreachable" whenever a dashboard loaded — found by watching the
    UI's health indicator flip to degraded, reproduced with concurrent
    requests. A missing file falls back to the original behaviour.
    """
    path = resolve_duckdb_path()
    try:
        if path.exists():
            with closing(duckdb.connect(str(path), read_only=True)) as conn:
                conn.execute("SELECT 1")
        else:
            with get_duckdb_connection() as conn:
                conn.execute("SELECT 1")
        return True
    except Exception:
        return False
