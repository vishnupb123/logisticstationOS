def test_list_scenarios_includes_the_shipped_files(client):
    response = client.get("/simulation/scenarios")

    assert response.status_code == 200
    filenames = {s["filename"] for s in response.json()}
    assert "rl_stow_balancing.yaml" in filenames
    assert "normal_operations.yaml" in filenames


def test_run_unknown_scenario_returns_404(client):
    response = client.post("/simulation/run", json={"scenario": "does_not_exist.yaml"})

    assert response.status_code == 404


def test_run_rejects_path_traversal_rather_than_reading_an_arbitrary_file(client):
    response = client.post("/simulation/run", json={"scenario": "../../../../etc/passwd"})

    # Path(filename).name strips the directory component before lookup
    # — this must resolve to "passwd" inside the scenarios dir (and
    # fail to find it there), never actually touch /etc/passwd.
    assert response.status_code == 404


def test_run_known_scenario_returns_a_real_summary(client):
    response = client.post("/simulation/run", json={"scenario": "rl_stow_balancing.yaml"})

    assert response.status_code == 200
    body = response.json()
    assert body["scenario_name"] == "rl_stow_balancing"
    assert body["source_kind"] == "simulated"
    assert body["event_count"] > 0
    assert sum(body["event_type_counts"].values()) == body["event_count"]


def test_run_with_seed_override_uses_the_requested_seed(client):
    response = client.post(
        "/simulation/run", json={"scenario": "rl_stow_balancing.yaml", "seed": 999}
    )

    assert response.status_code == 200
    assert response.json()["seed"] == 999
