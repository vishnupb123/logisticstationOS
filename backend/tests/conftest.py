import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import domain  # noqa: F401 — registers domain tables on Base.metadata
from app.db.postgres import Base, SessionLocal, engine
from app.events import models as event_models  # noqa: F401 — registers the events table
from app.main import app


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
