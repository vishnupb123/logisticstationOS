"""Test-suite bootstrap.

The suite runs against its own database, never the dev one: before any
`app` module is imported (and so before Settings is cached and the
SQLAlchemy engine is built), POSTGRES_DB is pointed at `<dev db>_test`,
which is created on demand. Previously the suite shared the dev
database, and the session-scoped `_schema` fixture's `drop_all` wiped
every application table the running app depended on (events,
decisions, agent executions) at the end of each `pytest` run — and
committed dev rows could break `.one()`-style assertions mid-run.
"""

import os

import psycopg
from psycopg import sql


def _use_isolated_test_database() -> None:
    # Settings() directly — not the lru_cached get_settings() — so .env
    # and env vars are honoured without caching the dev database name.
    from app.core.config import Settings

    base = Settings()
    test_db = base.postgres_db if base.postgres_db.endswith("_test") else f"{base.postgres_db}_test"
    os.environ["POSTGRES_DB"] = test_db
    try:
        with psycopg.connect(
            host=base.postgres_host,
            port=base.postgres_port,
            user=base.postgres_user,
            password=base.postgres_password.get_secret_value(),
            dbname="postgres",
            autocommit=True,
            connect_timeout=3,
        ) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (test_db,)
            ).fetchone()
            if not exists:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_db)))
    except psycopg.OperationalError:
        # Postgres unreachable: the `_schema` fixture below skips the
        # tests that need it, exactly as before.
        pass


_use_isolated_test_database()

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import domain  # noqa: F401 — registers domain tables on Base.metadata
from app.db.postgres import Base, SessionLocal, engine
from app.events import models as event_models  # noqa: F401 — registers the events table
from app.main import app
from app.orchestration import models as orchestration_models  # noqa: F401 — agent_executions
from app.security import models as security_models  # noqa: F401 — decision_records


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="session")
def _schema():
    """Session-scoped: creates every ORM-mapped table once, drops them
    once at the end. Skips (not fails) any test that depends on this when
    Postgres isn't reachable — same tolerant-but-honest posture as
    /health/ready, and consistent with this project's stance against
    mocking the database in tests that are supposed to verify real
    persistence behavior.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("PostgreSQL is not reachable — start it with `docker compose up -d postgres`")

    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(_schema):
    """One uncommitted transaction per test, rolled back at teardown.
    Application code under test only ever flushes, never commits, so this
    is sufficient for isolation without a savepoint-listener dance.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
