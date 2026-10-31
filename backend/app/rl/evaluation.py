"""Policy-evaluation logic shared by scripts/run_rl_evaluation.py (the
Milestone 6 baseline-comparison report) and app/security/decision_service.py
(Milestone 7's candidate-intervention evaluation) — one implementation
of "run this policy against this environment for one seeded episode
and aggregate across seeds," not two copies that could silently drift
apart.
"""

import statistics

import numpy as np

from app.rl.env import StowBalancingEnv

_AGGREGATE_KEYS = (
    "total_reward",
    "total_stowed",
    "max_jackpot_backlog",
    "constraint_violations",
    "steps",
    "mean_occupancy",
)


def run_episode(env: StowBalancingEnv, policy, seed: int) -> dict:
    obs, _info = env.reset(seed=seed)
    total_reward = 0.0
    total_stowed = 0
    max_backlog = 0
    constraint_violations = 0
    steps = 0
    occupancy_samples: list[float] = []
    terminated = truncated = False

    while not (terminated or truncated):
        action, _state = policy.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(np.asarray(action))
        total_reward += reward
        total_stowed += info["stowed_count"]
        max_backlog = max(max_backlog, info["jackpot_backlog"])
        constraint_violations += info["constraint_violations"]
        occupancy_samples.append(info["mean_hamper_occupancy"])
        steps += 1

    return {
        "seed": seed,
        "total_reward": total_reward,
        "total_stowed": total_stowed,
        "max_jackpot_backlog": max_backlog,
        "constraint_violations": constraint_violations,
        "steps": steps,
        "mean_occupancy": statistics.fmean(occupancy_samples) if occupancy_samples else 0.0,
        "terminated_cleanly": bool(terminated),
    }


def aggregate(results: list[dict]) -> dict:
    agg = {}
    for key in _AGGREGATE_KEYS:
        values = [r[key] for r in results]
        agg[f"{key}_mean"] = statistics.fmean(values)
        agg[f"{key}_stdev"] = statistics.pstdev(values) if len(values) > 1 else 0.0
    agg["episodes"] = len(results)
    cleanly = sum(1 for r in results if r["terminated_cleanly"])
    agg["terminated_cleanly_rate"] = cleanly / len(results)
    return agg


def evaluate_policy(env: StowBalancingEnv, policy, seeds: list[int]) -> dict:
    """run_episode + aggregate for one policy across a seed set — the
    "report expected outcomes with uncertainty" unit both the Milestone
    6 report and the Milestone 7 decision coordinator need.
    """
    episode_results = [run_episode(env, policy, seed) for seed in seeds]
    return {"episodes": episode_results, "aggregate": aggregate(episode_results)}
