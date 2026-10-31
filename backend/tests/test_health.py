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
