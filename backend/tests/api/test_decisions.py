"""HTTP-level tests for the decision-governance API — writes go
through the real `get_db` dependency and really commit, same as
`scripts/run_decision_demo.py`, so assertions check for the specific
record this test created rather than assuming an empty table (other
tests in this module/session may have already committed decisions).
"""

_SCENARIO = "rl_stow_balancing.yaml"
_CANDIDATES = [
    {
        "name": "status_quo",
        "description": "uniform priority",
        "priority_weights": {f"A{i}": 0.5 for i in range(1, 7)},
    },
    {
        "name": "tilted",
        "description": "tilted priority",
        "priority_weights": {f"A{i}": 0.9 if i <= 3 else 0.1 for i in range(1, 7)},
    },
]
_EVIDENCE = [{"category": "observation", "summary": "test evidence", "supporting_evidence": []}]


def _propose(client, *, shadow: bool = False) -> dict:
    response = client.post(
        "/decisions",
        json={
            "decision_type": "aisle_stow_priority",
            "context": {"trigger": "api test"},
            "evidence": _EVIDENCE,
            "scenario": _SCENARIO,
            "candidates": _CANDIDATES,
            "eval_seeds": [1, 2],
            "shadow": shadow,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_propose_decision_creates_a_pending_record(client, _schema):
    record = _propose(client)

    assert record["status"] == "pending_approval"
    assert len(record["candidates"]) == 2
    assert "policy_engine" in record["component_versions"]

    get_response = client.get(f"/decisions/{record['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == record["id"]


def test_propose_decision_unknown_scenario_returns_404(client, _schema):
    response = client.post(
        "/decisions",
        json={
            "decision_type": "aisle_stow_priority",
            "context": {},
            "evidence": _EVIDENCE,
            "scenario": "does_not_exist.yaml",
            "candidates": _CANDIDATES,
        },
    )
    assert response.status_code == 404


def test_propose_shadow_decision_has_shadow_status(client, _schema):
    record = _propose(client, shadow=True)

    assert record["status"] == "shadow"


def test_get_unknown_decision_returns_404(client, _schema):
    response = client.get("/decisions/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_list_decisions_includes_the_one_just_created(client, _schema):
    record = _propose(client)

    response = client.get("/decisions")
    assert response.status_code == 200
    ids = {d["id"] for d in response.json()}
    assert record["id"] in ids


def test_operator_cannot_approve_a_decision(client, _schema):
    record = _propose(client)

    response = client.post(
        f"/decisions/{record['id']}/approve",
        json={
            "approved_by": "api-operator",
            "approver_role": "operator",
            "selected_candidate": "tilted",
            "rationale": "x",
        },
    )

    assert response.status_code == 403


def test_supervisor_can_approve_a_decision(client, _schema):
    record = _propose(client)

    response = client.post(
        f"/decisions/{record['id']}/approve",
        json={
            "approved_by": "api-supervisor",
            "approver_role": "supervisor",
            "selected_candidate": "tilted",
            "rationale": "lower simulated backlog",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["approver_role"] == "supervisor"


def test_approve_unknown_candidate_returns_409(client, _schema):
    record = _propose(client)

    response = client.post(
        f"/decisions/{record['id']}/approve",
        json={
            "approved_by": "api-supervisor",
            "approver_role": "supervisor",
            "selected_candidate": "does_not_exist",
            "rationale": "x",
        },
    )

    assert response.status_code == 409


def test_shadow_decision_can_never_be_approved(client, _schema):
    record = _propose(client, shadow=True)

    response = client.post(
        f"/decisions/{record['id']}/approve",
        json={
            "approved_by": "api-admin",
            "approver_role": "admin",
            "selected_candidate": "tilted",
            "rationale": "x",
        },
    )

    assert response.status_code == 409


def test_reject_decision(client, _schema):
    record = _propose(client)

    response = client.post(
        f"/decisions/{record['id']}/reject",
        json={"approved_by": "api-supervisor", "approver_role": "supervisor", "rationale": "x"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_observe_outcome_without_approval_returns_409(client, _schema):
    record = _propose(client)

    response = client.post(
        f"/decisions/{record['id']}/observe-outcome",
        json={"scenario": _SCENARIO, "observe_seeds": [3, 4]},
    )

    assert response.status_code == 409


def test_observe_outcome_after_approval_returns_real_results(client, _schema):
    record = _propose(client)
    client.post(
        f"/decisions/{record['id']}/approve",
        json={
            "approved_by": "api-supervisor",
            "approver_role": "supervisor",
            "selected_candidate": "tilted",
            "rationale": "x",
        },
    )

    response = client.post(
        f"/decisions/{record['id']}/observe-outcome",
        json={"scenario": _SCENARIO, "observe_seeds": [3, 4]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["observed_outcome"] is not None
    assert "aggregate" in body["observed_outcome"]
