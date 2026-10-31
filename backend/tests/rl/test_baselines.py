import numpy as np

from app.rl.baselines import RuleBasedPolicy, StaticBaselinePolicy


def test_static_baseline_is_uniform_and_constant_across_observations():
    policy = StaticBaselinePolicy(n_aisles=4)

    action_a, _ = policy.predict(np.array([0.1, 0.9, 0.0, 0.5, 0.3, 0.2, 0.1]))
    action_b, _ = policy.predict(np.array([0.9, 0.1, 0.9, 0.9, 0.9, 0.9, 0.9]))

    assert np.array_equal(action_a, action_b)
    assert len(set(action_a.tolist())) == 1  # every aisle gets the same weight


def test_rule_based_baseline_mirrors_current_occupancy():
    policy = RuleBasedPolicy(n_aisles=3)
    obs = np.array([0.2, 0.9, 0.5, 0.1, 0.4, 0.3], dtype=np.float32)

    action, _ = policy.predict(obs)

    assert np.allclose(action, obs[:3])


def test_rule_based_baseline_reacts_to_different_observations():
    policy = RuleBasedPolicy(n_aisles=2)

    action_a, _ = policy.predict(np.array([0.1, 0.1, 0.0, 0.0], dtype=np.float32))
    action_b, _ = policy.predict(np.array([0.9, 0.2, 0.0, 0.0], dtype=np.float32))

    assert not np.array_equal(action_a, action_b)
