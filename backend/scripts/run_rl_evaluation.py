#!/usr/bin/env python3
"""Evaluation report for the stow-balancing RL environment
(docs/RL_ENVIRONMENT_SPEC.md "Evaluation protocol" / "Baseline
comparison"). Runs the static baseline, the rule-based baseline, and a
trained PPO policy against the training scenario AND two held-out
scenario variations, each across multiple seeds — never a single run,
never the training scenario alone.

This is a research-direction evaluation (ADR-0007), not a production
benchmark. Training reward increasing during scripts/train_rl_policy.py
is never itself evidence of improvement — only this comparison is.

Example:
    python scripts/run_rl_evaluation.py --policy ../ml/models/ppo_stow_balancing.zip \
        --out ../data/processed/rl_evaluation_report.json
"""

import argparse
import json
from pathlib import Path

from stable_baselines3 import PPO

from app.rl.baselines import RuleBasedPolicy, StaticBaselinePolicy
from app.rl.env import DEFAULT_DECISION_INTERVAL_SECONDS, DEFAULT_MAX_STEPS, StowBalancingEnv
from app.rl.evaluation import evaluate_policy
from app.simulation.config import load_scenario

_SCENARIOS = {
    "training": "../simulation/scenarios/rl_stow_balancing.yaml",
    "held_out_high_volume": "../simulation/scenarios/rl_stow_balancing_high_volume.yaml",
    "held_out_tighter_capacity": "../simulation/scenarios/rl_stow_balancing_tighter_capacity.yaml",
}
_EVAL_SEEDS = [101, 102, 103, 104, 105]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, help="path to a trained PPO .zip")
    parser.add_argument("--out", default="../data/processed/rl_evaluation_report.json")
    parser.add_argument(
        "--decision-interval-seconds", type=float, default=DEFAULT_DECISION_INTERVAL_SECONDS
    )
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    args = parser.parse_args()

    ppo_model = PPO.load(args.policy)

    report: dict = {
        "decision_interval_seconds": args.decision_interval_seconds,
        "max_steps": args.max_steps,
        "seeds": _EVAL_SEEDS,
        "scenarios": {},
    }

    for scenario_label, scenario_path in _SCENARIOS.items():
        config = load_scenario(scenario_path)
        env = StowBalancingEnv(
            config,
            decision_interval_seconds=args.decision_interval_seconds,
            max_steps=args.max_steps,
        )
        n_aisles = env.action_space.shape[0]

        policies = {
            "static_baseline": StaticBaselinePolicy(n_aisles),
            "rule_based_baseline": RuleBasedPolicy(n_aisles),
            "ppo": ppo_model,
        }

        scenario_report = {}
        print(f"--- {scenario_label} ({scenario_path}) ---")
        for policy_name, policy in policies.items():
            result = evaluate_policy(env, policy, _EVAL_SEEDS)
            agg = result["aggregate"]
            scenario_report[policy_name] = result
            print(
                f"  {policy_name}: reward={agg['total_reward_mean']:.2f}"
                f"±{agg['total_reward_stdev']:.2f} stowed={agg['total_stowed_mean']:.1f} "
                f"backlog={agg['max_jackpot_backlog_mean']:.1f} "
                f"violations={agg['constraint_violations_mean']:.1f}"
            )
        report["scenarios"][scenario_label] = scenario_report

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
