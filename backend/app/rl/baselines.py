"""Baseline policies for the stow-balancing evaluation
(docs/RL_ENVIRONMENT_SPEC.md "Baseline comparison" — not optional:
every trained policy is compared against these before any improvement
claim). Both expose `.predict(obs) -> (action, state)`, the same shape
Stable-Baselines3 policies use, so one evaluation loop
(backend/scripts/run_rl_evaluation.py) drives all three policy types
identically.
"""

import numpy as np


class StaticBaselinePolicy:
    """No reallocation: every aisle gets the same priority weight,
    every step, regardless of state. Bucketed priority translation
    (app/rl/env.py::AisleStowPriorityController) means this is genuine
    no-preference FIFO at the resource level, not an arbitrary-but-
    fixed aisle ordering — the same behavior the twin had before
    Milestone 6 introduced a priority hook at all.
    """

    def __init__(self, n_aisles: int):
        self._action = np.full(n_aisles, 0.5, dtype=np.float32)

    def predict(self, obs, state=None, episode_start=None, deterministic=True):
        return self._action, None


class RuleBasedPolicy:
    """Heuristic, not learned or tuned: prioritize whichever aisle
    currently has the highest hamper occupancy — "fight the fire
    that's most on fire." A reasonable guess at a sensible rule, which
    is exactly the point of a rule-based baseline: something a human
    might actually write, to compare a learned policy against.
    """

    def __init__(self, n_aisles: int):
        self._n = n_aisles

    def predict(self, obs, state=None, episode_start=None, deterministic=True):
        occupancy = np.asarray(obs[: self._n], dtype=np.float32)
        return occupancy, None
