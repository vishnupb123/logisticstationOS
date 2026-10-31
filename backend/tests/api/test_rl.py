def test_evaluate_unknown_scenario_returns_404(client):
    response = client.post("/rl/evaluate", json={"scenario": "does_not_exist.yaml"})

    assert response.status_code == 404


def test_evaluate_rejects_the_trained_ppo_policy_name(client):
    response = client.post(
        "/rl/evaluate",
        json={"scenario": "rl_stow_balancing.yaml", "policies": ["ppo"]},
    )

    assert response.status_code == 422


def test_evaluate_runs_both_baselines_for_real(client):
    response = client.post(
        "/rl/evaluate",
        json={"scenario": "rl_stow_balancing.yaml", "seeds": [1, 2]},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["results"]) == {"static_baseline", "rule_based_baseline"}
    for result in body["results"].values():
        assert len(result["episodes"]) == 2
        assert "total_reward_mean" in result["aggregate"]
