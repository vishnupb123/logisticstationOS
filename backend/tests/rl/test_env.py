"""Tests for StowBalancingEnv. No database, no dbt, no trained model —
pure environment mechanics, run directly against the shipped
rl_stow_balancing scenario and small hand-built configs.
"""

from pathlib import Path

import numpy as np

from app.rl.env import MIN_PRIORITY_WEIGHT, AisleStowPriorityController, StowBalancingEnv
from app.simulation.config import ScenarioConfig, load_scenario

_SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "simulation" / "scenarios"


def _small_config(**overrides) -> ScenarioConfig:
    base = {
        "name": "rl-test",
        "seed": 7,
        "station_layout": {
            "cluster_a_aisle_count": 3,
            "cluster_b_aisle_count": 0,
            "hamper_capacity": 2,
        },
        "truck_arrivals": {"truck_count": 2, "arrival_interval_minutes": 3},
        "parcels": {"parcels_per_truck": 15, "stow_duration_seconds": 25},
        "resources": {"induct_capacity": 1, "stower_count": 1, "jackpot_clear_interval_minutes": 2},
    }
    base.update(overrides)
    return ScenarioConfig.model_validate(base)


def test_spaces_match_aisle_count():
    config = _small_config()
    env = StowBalancingEnv(config)

    assert env.action_space.shape == (3,)
    assert env.observation_space.shape == (6,)  # 3 aisles + stower util + backlog + time


def test_reset_returns_observation_within_bounds():
    env = StowBalancingEnv(_small_config())
    obs, info = env.reset(seed=1)

    assert env.observation_space.contains(obs)
    assert info == {}


def test_same_seed_and_actions_produce_identical_trajectory():
    config = _small_config()

    def run():
        env = StowBalancingEnv(config, decision_interval_seconds=60.0, max_steps=50)
        obs, _ = env.reset(seed=3)
        trace = []
        for i in range(50):
            action = np.full(3, 0.3 + 0.1 * (i % 3), dtype=np.float32)
            obs, reward, terminated, truncated, info = env.step(action)
            trace.append((reward, terminated, truncated, tuple(obs.tolist())))
            if terminated or truncated:
                break
        return trace

    assert run() == run()


def test_episode_eventually_terminates_cleanly():
    env = StowBalancingEnv(_small_config(), decision_interval_seconds=60.0, max_steps=200)
    obs, _ = env.reset(seed=4)

    terminated = truncated = False
    steps = 0
    while not (terminated or truncated) and steps < 200:
        obs, reward, terminated, truncated, info = env.step(np.full(3, 0.5, dtype=np.float32))
        steps += 1

    assert terminated, "episode should close once all trucks/parcels resolve, within the horizon"
    assert not truncated


def test_shipped_training_scenario_loads_and_runs():
    config = load_scenario(_SCENARIOS_DIR / "rl_stow_balancing.yaml")
    env = StowBalancingEnv(config)
    obs, _ = env.reset(seed=10)

    for _ in range(5):
        obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
        assert isinstance(reward, float)
        assert "constraint_violations" in info
        if terminated or truncated:
            break


class TestAisleStowPriorityController:
    def test_uniform_weights_produce_true_ties_not_an_arbitrary_ranking(self):
        codes = ["A1", "A2", "A3"]
        controller = AisleStowPriorityController(codes)
        controller.set_weights(np.array([0.5, 0.5, 0.5], dtype=np.float32))

        priorities = [controller.priority_for(c) for c in codes]
        assert priorities[0] == priorities[1] == priorities[2]

    def test_differentiated_weights_produce_different_priorities(self):
        codes = ["A1", "A2", "A3"]
        controller = AisleStowPriorityController(codes)
        controller.set_weights(np.array([0.9, 0.1, 0.5], dtype=np.float32))

        priorities = [controller.priority_for(c) for c in codes]
        assert len(set(priorities)) > 1
        assert priorities[0] < priorities[1]  # higher weight -> better (lower) priority number

    def test_hard_constraint_never_lets_a_weight_reach_zero(self):
        codes = ["A1", "A2"]
        controller = AisleStowPriorityController(codes)
        controller.set_weights(np.array([1.0, 0.0], dtype=np.float32))

        assert controller.last_action_was_clipped is True
        # A2's effective weight was floored to MIN_PRIORITY_WEIGHT, not 0 —
        # verified indirectly: its priority is worse than A1's but still
        # a finite, bounded value (never "never served").
        assert controller.priority_for("A2") >= controller.priority_for("A1")
        assert MIN_PRIORITY_WEIGHT > 0

    def test_action_at_or_above_floor_is_not_flagged_as_clipped(self):
        codes = ["A1", "A2"]
        controller = AisleStowPriorityController(codes)
        controller.set_weights(np.array([0.8, MIN_PRIORITY_WEIGHT], dtype=np.float32))

        assert controller.last_action_was_clipped is False
