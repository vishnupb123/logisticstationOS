from fastapi.testclient import TestClient


def test_liveness(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_both_dependencies(client: TestClient) -> None:
    # Runs with no live Postgres/DuckDB in CI, so this only asserts the
    # endpoint responds and reports per-dependency status — not that the
    # dependencies are actually reachable.
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert set(body["dependencies"]) == {"postgres", "duckdb"}
    assert body["dependencies"]["postgres"] in {"ok", "unreachable"}
    assert body["dependencies"]["duckdb"] in {"ok", "unreachable"}


def test_duckdb_probe_succeeds_while_a_read_only_connection_is_open(monkeypatch, tmp_path):
    # Regression: the probe used to open read-write, which DuckDB refuses
    # while another in-process read-only connection to the same file is
    # open — so the readiness check reported "unreachable" whenever the
    # analytics routes were serving a dashboard at the same moment.
    import duckdb

    from app.db import duckdb as duckdb_db

    db_path = tmp_path / "analytics.duckdb"
    duckdb.connect(str(db_path)).close()
    monkeypatch.setattr(duckdb_db, "resolve_duckdb_path", lambda: db_path)

    reader = duckdb.connect(str(db_path), read_only=True)
    try:
        assert duckdb_db.check_connection() is True
    finally:
        reader.close()
