from fastapi import APIRouter

from app.db import duckdb as duckdb_db
from app.db import postgres as postgres_db

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness() -> dict:
    """Process-level liveness check — no external dependencies."""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness() -> dict:
    """Readiness check — reports reachability of each backing store.

    Returns 200 even when a dependency is unreachable so the response body
    (not the HTTP status) carries the per-dependency detail. Orchestration
    tooling that wants a hard pass/fail signal should inspect the body.
    """
    postgres_ok = postgres_db.check_connection()
    duckdb_ok = duckdb_db.check_connection()
    return {
        "status": "ok" if (postgres_ok and duckdb_ok) else "degraded",
        "dependencies": {
            "postgres": "ok" if postgres_ok else "unreachable",
            "duckdb": "ok" if duckdb_ok else "unreachable",
        },
    }
