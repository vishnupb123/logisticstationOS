"""HTTP tests for station-ops, truckfile and the agent -> approval flow.
The agent run uses an unreachable Ollama URL on purpose so the test is
environment-independent: it must come back DEGRADED with complete
deterministic output, never FAILED."""

import json

from app.core.config import get_settings


def test_presets_and_metric_definitions(client):
    names = {p["name"] for p in client.get("/station-ops/presets").json()}
    assert {"normal_day", "ferry_disruption", "peak_volume"} <= names
    defs = client.get("/station-ops/metric-definitions").json()
    assert all(m["status"] == "proposed" for m in defs["metrics"].values())


def test_run_day_and_policy_bounds(client):
    r = client.post("/station-ops/run-day", json={"preset": "induct_line_outage"})
    assert r.status_code == 200
    base = r.json()["metrics"]["dea"]["value"]
    r = client.post(
        "/station-ops/run-day",
        json={
            "preset": "induct_line_outage",
            "interventions": [{"kind": "open_induct_line", "amount": 1, "at_minute": 120}],
        },
    )
    assert r.json()["metrics"]["dea"]["value"] > base
    r = client.post(
        "/station-ops/run-day",
        json={
            "preset": "normal_day",
            "interventions": [{"kind": "add_stowers", "amount": 50, "at_minute": 120}],
        },
    )
    assert r.status_code == 422
    assert client.post("/station-ops/run-day", json={"preset": "nope"}).status_code == 404


def test_live_stream_progresses_and_terminates(client):
    frames = []
    with client.stream(
        "GET",
        "/station-ops/live",
        params={
            "preset": "induct_line_outage",
            "mode": "autopilot",
            "learn": "false",
            "step_minutes": 30,
            "frame_interval_ms": 0,
        },
    ) as r:
        assert r.status_code == 200
        event = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event == "frame":
                frames.append(json.loads(line[6:]))
    minutes = [f["snapshot"]["minute"] for f in frames]
    assert minutes == sorted(minutes) and frames[-1]["snapshot"]["done"]
    assert any(f["agent"]["new_actions"] for f in frames)


def test_truckfile_refresh_and_twin_from_truckfile(client, _schema):
    day = "2026-12-01"
    assert client.get("/inbound/truckfile", params={"ofd_date": day}).json()["exists"] is False
    r = client.post("/inbound/truckfile/refresh", json={"ofd_date": day, "weather": "rough"})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["delayed"] > 0
    assert any(t["revised_arrival"] for t in body["trips"] if t["via_ferry"])
    r = client.post(
        "/station-ops/run-day",
        json={"preset": "normal_day", "source": "truckfile", "ofd_date": day},
    )
    assert r.status_code == 200 and r.json()["scenario"] == f"truckfile_{day}"


def test_agent_run_degrades_proposes_and_flows_through_approval(client, _schema, monkeypatch):
    monkeypatch.setattr(get_settings(), "ollama_base_url", "http://127.0.0.1:9")
    r = client.post(
        "/agents/station-ops/run", json={"preset": "induct_line_outage", "until_minute": 240}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["execution"]["status"] == "degraded"
    assert body["execution"]["output"]["findings"]
    assert body["decision_ids"]

    decision = client.get(f"/decisions/{body['decision_ids'][0]}").json()
    assert decision["decision_type"] == "station_ops_mitigation"
    assert decision["status"] == "pending_approval"
    assert decision["policy_engine_result"]["eligible"] is True

    # operators cannot decide; supervisors can
    best = decision["candidates"][0]["name"]
    denied = client.post(
        f"/decisions/{decision['id']}/approve",
        json={
            "approved_by": "op",
            "approver_role": "operator",
            "selected_candidate": best,
            "rationale": "x",
        },
    )
    assert denied.status_code == 403
    ok = client.post(
        f"/decisions/{decision['id']}/approve",
        json={
            "approved_by": "sup",
            "approver_role": "supervisor",
            "selected_candidate": best,
            "rationale": "approved in test",
        },
    )
    assert ok.status_code == 200
    observed = client.post(
        f"/decisions/{decision['id']}/observe-outcome", json={"observe_seeds": [301]}
    )
    assert observed.status_code == 200
    outcome = observed.json()["observed_outcome"]
    assert outcome["kind"] == "simulated_rerun_on_fresh_seeds"
    assert len(outcome["episodes"]) == 1

    pb = client.get("/agents/station-ops/playbook").json()
    assert pb["episodes"] > 0 and pb["stats"]


def test_llm_status_reports_availability(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "ollama_base_url", "http://127.0.0.1:9")
    body = client.get("/llm/status").json()
    assert body["available"] is False and body["model"]
