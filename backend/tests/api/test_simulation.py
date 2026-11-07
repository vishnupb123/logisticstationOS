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


def _parse_sse(text: str) -> list[tuple[str, str]]:
    frames = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        frames.append((lines["event"], lines["data"]))
    return frames


def test_live_stream_plays_back_the_twin_to_completion(client):
    import json

    response = client.get(
        "/simulation/live",
        params={"scenario": "rl_stow_balancing.yaml", "step_seconds": 60, "frame_interval_ms": 0},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = _parse_sse(response.text)
    assert frames[-1][0] == "end"
    snapshots = [json.loads(data) for kind, data in frames if kind == "snapshot"]
    assert len(snapshots) > 3
    assert all(s["source_kind"] == "simulated" for s in snapshots)
    # Monotonic progress: simulated time and stowed count never go backwards.
    times = [s["sim_time_seconds"] for s in snapshots]
    stowed = [s["funnel"]["parcels_stowed"] for s in snapshots]
    assert times == sorted(times)
    assert stowed == sorted(stowed)
    final = snapshots[-1]
    assert final["done"] is True
    # Every planned parcel reached a terminal state, and nothing is left in WIP.
    assert (
        final["funnel"]["parcels_stowed"] + final["funnel"]["parcels_exception"]
        == (final["planned_parcels"])
    )
    assert sum(final["wip"].values()) == 0
    assert final["cycle_times"]["dock_to_stow"]["count"] == final["funnel"]["parcels_stowed"]


def test_live_stream_counts_match_the_batch_run(client):
    import json

    batch = client.post("/simulation/run", json={"scenario": "normal_operations.yaml"}).json()
    response = client.get(
        "/simulation/live",
        params={"scenario": "normal_operations.yaml", "frame_interval_ms": 0},
    )
    final = json.loads([data for kind, data in _parse_sse(response.text) if kind == "snapshot"][-1])

    counts = batch["event_type_counts"]
    assert final["funnel"]["parcels_inducted"] == counts["parcel.inducted"]
    assert final["funnel"]["parcels_stowed"] == counts["parcel.stowed"]
    assert final["funnel"]["jackpot_clears"] == counts.get("parcel.jackpot_cleared", 0)


def test_live_stream_rejects_unknown_and_traversal_scenarios(client):
    assert client.get("/simulation/live", params={"scenario": "nope.yaml"}).status_code == 404
    assert (
        client.get("/simulation/live", params={"scenario": "../../../../etc/passwd"}).status_code
        == 404
    )


def test_live_stream_bounds_its_parameters(client):
    params = {"scenario": "rl_stow_balancing.yaml"}
    assert client.get("/simulation/live", params={**params, "step_seconds": 0}).status_code == 422
    assert (
        client.get("/simulation/live", params={**params, "frame_interval_ms": 99999}).status_code
        == 422
    )
