from tests.helpers.duckdb_fixtures import build_metrics_duckdb


def test_get_execution_404(client, _schema):
    missing_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/agents/flow-intelligence/executions/{missing_id}")
    assert response.status_code == 404


def test_list_executions_returns_a_list(client, _schema):
    response = client.get("/agents/flow-intelligence/executions")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_run_persists_and_returns_an_execution_with_deterministic_findings(
    client, _schema, monkeypatch, tmp_path
):
    """Doesn't assume anything about whether a real Ollama server is
    reachable on this machine — that would make the test
    environment-dependent and flaky. Only asserts what's guaranteed
    regardless: the deterministic findings are always present, and the
    execution is actually persisted and returned.
    """
    import app.api.routes.agents as route

    db_path = tmp_path / "metrics.duckdb"
    build_metrics_duckdb(db_path, cumulative_diverts=5, cumulative_clears=1, wip_count=3)
    monkeypatch.setattr(route, "resolve_duckdb_path", lambda: db_path)

    response = client.post("/agents/flow-intelligence/run")

    assert response.status_code == 200
    body = response.json()
    assert body["agent_name"] == "flow_intelligence"
    assert body["output"] is not None
    findings = body["output"]["findings"]
    categories = [f["category"] for f in findings]
    assert "observation" in categories

    get_response = client.get(f"/agents/flow-intelligence/executions/{body['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == body["id"]
