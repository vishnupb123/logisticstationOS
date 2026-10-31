"""StowBalancingEnv: a Gymnasium environment wrapping the Milestone 4
digital twin (app/simulation/model.py), for the narrow decision problem
selected by the project owner (ADR-0007 amendment): **aisle-level stow
capacity and workload balancing under variable inbound flow**.

Status: research direction, per docs/RL_ENVIRONMENT_SPEC.md — everything
below is this milestone's first formalization attempt, not a validated
design.

## The actual decision

Before this milestone, the twin's stower pool served stow requests
strictly FIFO by arrival, with no notion of "aisle" at all — there was
no workload-balancing decision surface to learn over. This environment
introduces one: every `decision_interval_seconds` of simulated time, the
policy sets a relative priority weight per aisle; those weights become
SimPy `PriorityResource` priorities for stow requests arriving during
the next interval (app/simulation/model.py's `StowPriorityProvider`
hook, added for exactly this). Nothing about capacity itself is
controlled — the policy can only reorder who gets served next among
*existing* eligible work, never summon extra stower capacity. That's
a hard constraint satisfied by the action space's own shape, not a
reward penalty.

## Observation (Box, shape = n_aisles + 3)

- One value per aisle: current hamper occupancy (level / capacity), in
  [0, 1]. Maps to the "aisle workload" / "hamper occupancy" candidate
  state variables (docs/RL_ENVIRONMENT_SPEC.md).
- Stower utilization: fraction of the stower pool currently busy.
- Jackpot backlog, normalized by a rough capacity ceiling (n_aisles *
  hamper_capacity) and clipped to [0, 1].
- Fraction of the episode horizon elapsed.

This is intentionally a local, partial view (no truck-level detail, no
individual parcel identity) — a real floor supervisor doesn't see a
global ledger either (docs/RL_ENVIRONMENT_SPEC.md "Partial
observability").

## Action (Box, shape = n_aisles, values in [0, 1])

A relative priority weight per aisle for the upcoming interval. Higher
= served first. **Hard constraint, enforced structurally, not as a
reward penalty**: a weight is never allowed to fall to zero — every
weight is clipped to at least `MIN_PRIORITY_WEIGHT` before being turned
into a priority rank, so no aisle can be indefinitely starved
regardless of what the policy outputs. Every time an incoming action
actually required clipping, `info["constraint_violations"]` on that
step is 1 (0 otherwise) — a real, counted hard-constraint-enforcement
event for the evaluation report, not just a theoretical possibility.

## Reward (per decision interval)

    reward = stowed_count - JACKPOT_BACKLOG_WEIGHT * jackpot_backlog_delta
             - OCCUPANCY_PENALTY_WEIGHT * mean_hamper_occupancy

- `stowed_count`: parcels stowed this interval — the "stow throughput"
  metric contract (docs/OPERATIONAL_DOMAIN_MODEL.md §4.1, `proposed`
  status), per-interval rather than per-hour.
- `jackpot_backlog_delta`: net *new* backlog this interval (diverts
  minus clears, delta form of the `proposed` "jackpot volume" metric).
- `mean_hamper_occupancy`: **not** one of the metric-contract metrics —
  an added reward-shaping term, flagged explicitly as such per
  docs/RL_ENVIRONMENT_SPEC.md's own warning against presenting an
  invented proxy as authoritative. It exists to give the policy signal
  between jackpot events, which are otherwise sparse.

## What this is not

Not a claim that the problem is well-posed, that this reward is
correct, or that any trained policy generalizes — see
backend/scripts/run_rl_evaluation.py and docs/RL_ENVIRONMENT_SPEC.md
for what was actually measured.
"""

import numpy as np
from gymnasium import Env, spaces

from app.events.event_types import (
    PARCEL_JACKPOT_CLEARED,
    PARCEL_SORT_ATTEMPTED,
    PARCEL_STOWED,
)
from app.simulation.config import ScenarioConfig
from app.simulation.model import aisle_codes_for, setup_simulation

MIN_PRIORITY_WEIGHT = 0.05
JACKPOT_BACKLOG_WEIGHT = 0.5
OCCUPANCY_PENALTY_WEIGHT = 1.0
# A 300s/60-step default was tried first and found empirically to never
# create real contention — with ample stow capacity relative to volume,
# hampers fully drained between decisions, so no policy could
# distinguish itself from any other (verified: a uniform-priority and
# an occupancy-greedy fixed policy produced byte-identical trajectories
# on the same seed). 60s/200 is the validated default — it's what
# simulation/scenarios/rl_stow_balancing.yaml was tuned against.
DEFAULT_DECISION_INTERVAL_SECONDS = 60.0
DEFAULT_MAX_STEPS = 200


class AisleStowPriorityController:
    """The StowPriorityProvider the environment hands to the twin
    (app/simulation/model.py) — translates the policy's continuous
    weights into SimPy priority ranks, enforcing the anti-starvation
    floor described in this module's docstring.
    """

    #: Weights are bucketed into this many discrete priority levels
    #: rather than fully ranked (argsort would give every aisle a
    #: distinct priority integer, so two genuinely-equal weights would
    #: still be arbitrarily broken by aisle index — never truly tied).
    #: Bucketing lets equal/near-equal weights collapse onto the same
    #: priority value, so SimPy's own FIFO-by-request-time tie-break
    #: applies — which is what makes a uniform action (the static
    #: baseline) behave as genuine no-preference FIFO, not a fixed
    #: arbitrary aisle ordering.
    _PRIORITY_LEVELS = 10

    def __init__(self, aisle_codes: list[str]):
        self._aisle_codes = aisle_codes
        self._priority_by_aisle: dict[str, int] = {code: 0 for code in aisle_codes}
        self.last_action_was_clipped = False

    def set_weights(self, weights: np.ndarray) -> None:
        clipped_to_unit = np.clip(weights, 0.0, 1.0)
        floored = np.clip(clipped_to_unit, MIN_PRIORITY_WEIGHT, None)
        self.last_action_was_clipped = bool(np.any(floored != clipped_to_unit))

        levels = np.clip(
            (floored * self._PRIORITY_LEVELS).astype(int), 0, self._PRIORITY_LEVELS - 1
        )
        priorities = (self._PRIORITY_LEVELS - 1) - levels  # higher weight -> lower priority value
        for code, priority in zip(self._aisle_codes, priorities, strict=True):
            self._priority_by_aisle[code] = int(priority)

    def priority_for(self, aisle_code: str) -> int:
        return self._priority_by_aisle.get(aisle_code, 0)


class StowBalancingEnv(Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        scenario_config: ScenarioConfig,
        *,
        decision_interval_seconds: float = DEFAULT_DECISION_INTERVAL_SECONDS,
        max_steps: int = DEFAULT_MAX_STEPS,
    ):
        super().__init__()
        self._base_config = scenario_config
        self._decision_interval = decision_interval_seconds
        self._max_steps = max_steps
        self._aisle_codes = aisle_codes_for(scenario_config)
        n = len(self._aisle_codes)

        self.action_space = spaces.Box(low=0.0, high=1.0, shape=(n,), dtype=np.float32)
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(n + 3,), dtype=np.float32)

        self._controller: AisleStowPriorityController | None = None
        self._env = None
        self._ctx = None
        self._step_count = 0
        self._prev_event_count = 0
        self._prev_diverts = 0
        self._prev_clears = 0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        config = (
            self._base_config
            if seed is None
            else self._base_config.model_copy(update={"seed": seed})
        )

        self._controller = AisleStowPriorityController(self._aisle_codes)
        self._env, self._ctx = setup_simulation(config, stow_priority_provider=self._controller)
        self._step_count = 0
        self._prev_event_count = 0
        self._prev_diverts = 0
        self._prev_clears = 0

        return self._observe(), {}

    def step(self, action):
        self._controller.set_weights(np.asarray(action, dtype=np.float32))

        target_time = self._env.now + self._decision_interval
        self._env.run(until=target_time)

        new_events = self._ctx.events[self._prev_event_count :]
        self._prev_event_count = len(self._ctx.events)

        stowed_count = sum(1 for e in new_events if e.event_type == PARCEL_STOWED)

        total_diverts = sum(
            1
            for e in self._ctx.events
            if e.event_type == PARCEL_SORT_ATTEMPTED and e.payload.get("outcome") == "jackpot"
        )
        total_clears = sum(1 for e in self._ctx.events if e.event_type == PARCEL_JACKPOT_CLEARED)
        backlog_now = total_diverts - total_clears
        backlog_delta = backlog_now - (self._prev_diverts - self._prev_clears)
        self._prev_diverts, self._prev_clears = total_diverts, total_clears

        mean_occupancy = self._mean_hamper_occupancy()

        reward = (
            stowed_count
            - JACKPOT_BACKLOG_WEIGHT * max(backlog_delta, 0)
            - OCCUPANCY_PENALTY_WEIGHT * mean_occupancy
        )

        self._step_count += 1
        episode_closed = (
            self._ctx.trucks_remaining.value == 0 and self._ctx.parcels_in_flight.value == 0
        )
        terminated = bool(episode_closed)
        truncated = self._step_count >= self._max_steps

        info = {
            "stowed_count": stowed_count,
            "jackpot_backlog": backlog_now,
            "mean_hamper_occupancy": mean_occupancy,
            "constraint_violations": int(self._controller.last_action_was_clipped),
        }
        return self._observe(), float(reward), terminated, truncated, info

    def _mean_hamper_occupancy(self) -> float:
        occupancies = [
            self._ctx.hampers[code].level / self._ctx.hampers[code].capacity
            for code in self._aisle_codes
        ]
        return float(np.mean(occupancies)) if occupancies else 0.0

    def _observe(self) -> np.ndarray:
        occupancies = [
            self._ctx.hampers[code].level / self._ctx.hampers[code].capacity
            for code in self._aisle_codes
        ]
        stower_util = self._stower_utilization()

        backlog_now = self._prev_diverts - self._prev_clears
        hamper_capacity = self._base_config.station_layout.hamper_capacity
        backlog_ceiling = max(len(self._aisle_codes) * hamper_capacity, 1)
        backlog_norm = min(max(backlog_now, 0) / backlog_ceiling, 1.0)

        time_frac = min(self._env.now / (self._max_steps * self._decision_interval), 1.0)

        obs = np.array([*occupancies, stower_util, backlog_norm, time_frac], dtype=np.float32)
        return np.clip(obs, 0.0, 1.0)

    def _stower_utilization(self) -> float:
        capacity = self._ctx.stower_pool.capacity
        in_use = len(self._ctx.stower_pool.users)
        return in_use / capacity if capacity else 0.0
