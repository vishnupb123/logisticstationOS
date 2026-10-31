#!/usr/bin/env python3
"""Train a PPO policy for the stow-balancing decision problem
(docs/RL_ENVIRONMENT_SPEC.md). PPO is a candidate baseline per
ADR-0007, not a mandated solution — training reward increasing here is
never itself evidence of improvement; see
scripts/run_rl_evaluation.py for the actual comparison against
baselines on held-out scenarios.

Example:
    python scripts/train_rl_policy.py \
        --scenario ../simulation/scenarios/rl_stow_balancing.yaml \
        --timesteps 50000 --seed 0 --out ../ml/models/ppo_stow_balancing.zip
"""

import argparse
from pathlib import Path

from stable_baselines3 import PPO

from app.rl.env import DEFAULT_DECISION_INTERVAL_SECONDS, DEFAULT_MAX_STEPS, StowBalancingEnv
from app.simulation.config import load_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, help="path to a training scenario YAML")
    parser.add_argument("--timesteps", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--decision-interval-seconds", type=float, default=DEFAULT_DECISION_INTERVAL_SECONDS
    )
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--out", required=True, help="output path for the trained policy (.zip)")
    args = parser.parse_args()

    config = load_scenario(args.scenario)
    env = StowBalancingEnv(
        config,
        decision_interval_seconds=args.decision_interval_seconds,
        max_steps=args.max_steps,
    )

    model = PPO("MlpPolicy", env, seed=args.seed, verbose=1, n_steps=128, batch_size=64)
    model.learn(total_timesteps=args.timesteps)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(out_path))
    print(f"saved trained policy to {out_path}")


if __name__ == "__main__":
    main()
