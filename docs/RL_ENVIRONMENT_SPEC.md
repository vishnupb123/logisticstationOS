# Reinforcement Learning Environment Specification

## Status: first formalization implemented and evaluated (Milestone 6, 2026-10-31)

The design space below was "open, not finalized" at the start of this milestone. It's now implemented, tested, and evaluated — but the evaluation's own finding is that the implemented reward does not clearly translate into an operationally meaningful improvement (see "Evaluation results" below). Treat this as a first, honest attempt at formalizing the problem, not a validated solution.

## Research question

> Can a hierarchical, agent-coordinated reinforcement learning architecture improve decision-making in partially observable, capacity-constrained logistics operations, compared with conventional rule-based and isolated optimisation approaches?

Still a hypothesis, not a result — this milestone investigates one small piece of it (a single-agent, non-hierarchical narrow problem) and finds a cautionary result worth reporting rather than a confirming one. See "Evaluation results."

## Stack

Gymnasium 1.0 + Stable-Baselines3 2.9 + PyTorch 2.15, installed as the `rl` extra (`backend/pyproject.toml`) — not a base dependency; offline training/evaluation tools run via `backend/scripts/`, not invoked by the FastAPI app, same reasoning as dbt's `analytics` extra. PPO is the implemented candidate; no other algorithm was evaluated this milestone.

## The decision problem, as actually formalized

**Problem (ADR-0007 amendment): aisle-level stow capacity and workload balancing under variable inbound flow.**

Before this milestone, the digital twin's stower pool served stow requests strictly FIFO by arrival — there was no "aisle" concept in that queue at all, so there was nothing for a policy to balance. Milestone 6 added a real decision point: `backend/app/simulation/model.py::StowPriorityProvider`, a hook the twin consults for a per-aisle priority value whenever a parcel requests a stower. The RL environment (`backend/app/rl/env.py::StowBalancingEnv`) is what sets that hook, once per decision interval.

**What the policy controls**: a relative priority weight per aisle for the next 60 seconds of simulated time. **What it never controls**: how many stowers exist, or whether any specific unit of work gets skipped — the action space can only reorder *existing* eligible work among aisles, never fabricate or destroy capacity. That's the hard constraint, and it's true by construction (the action space's own shape), not something that needs policing.

### State (observation space: `Box`, shape = n_aisles + 3)

| Index | Meaning | Candidate variable it maps to |
|---|---|---|
| `0..n-1` | Per-aisle hamper occupancy (`level / capacity`), in [0, 1] | "aisle workload" / "hamper occupancy" |
| `n` | Stower pool utilization (fraction busy) | "stower availability" |
| `n+1` | Jackpot backlog, normalized by a rough ceiling (`n_aisles * hamper_capacity`) | "jackpot backlog" |
| `n+2` | Fraction of the episode horizon elapsed | "remaining processing time" |

Deliberately local and partial — no truck-level detail, no individual parcel identity, no global ledger a real floor supervisor wouldn't have either.

**Not implemented from the candidate list**: "induct throughput" and "demand uncertainty" as explicit state — the former is implicitly reflected in how fast hamper occupancy rises, the latter isn't modeled as a distinct signal (the policy only ever sees what's already happened, not a forecast). Noted as a real simplification, not an oversight.

### Action (`Box`, shape = n_aisles, values in [0, 1])

A priority weight per aisle. **Hard constraint, enforced structurally** (`AisleStowPriorityController` in `app/rl/env.py`): every weight is floored to `MIN_PRIORITY_WEIGHT` (0.05) before being converted to a priority rank — no aisle can be driven to zero and left indefinitely unserved, regardless of what the policy outputs. Weights are bucketed into 10 discrete priority levels (not a full ranking) specifically so that *genuinely equal* weights collapse onto the same priority value and get served in true FIFO order by the twin itself — this is what makes "uniform weights" (the static baseline) behave as real no-preference FIFO rather than an arbitrary-but-fixed aisle ordering, which a naive full `argsort` would have produced instead (caught and fixed during this milestone — see `HANDOFF.md`).

Every step where an incoming action actually required flooring is counted in `info["constraint_violations"]` — a real, measured count of the hard constraint firing, not a theoretical possibility.

### Reward (per decision interval)

```
reward = stowed_count
         - 0.5 * max(jackpot_backlog_delta, 0)
         - 1.0 * mean_hamper_occupancy
```

- `stowed_count`: parcels stowed this interval — the per-interval form of the **`proposed`**-status "stow throughput" metric (`docs/OPERATIONAL_DOMAIN_MODEL.md` §4.1).
- `jackpot_backlog_delta`: net *new* backlog this interval (diverts minus clears) — the delta form of the **`proposed`**-status "jackpot volume" metric.
- `mean_hamper_occupancy`: **explicitly not a metric-contract entry** — an added reward-shaping term, flagged here exactly as the spec warns against presenting an invented proxy as authoritative. It exists to give the policy a dense signal between the comparatively sparse jackpot events. **This term turned out to matter a lot — see the finding below.**

### What was tuned, and what that revealed

The first scenario attempt (`hamper_capacity=4`, `stower_count=2`, 5-minute decision interval) looked constrained on paper but, when actually tested, never created a situation where any hamper hit its capacity — stow throughput is capacity-bound regardless of service order, so a uniform-priority policy and an occupancy-greedy policy produced **byte-identical trajectories** on the same seed. This was caught empirically, not assumed away: `simulation/scenarios/rl_stow_balancing.yaml` was retuned (`hamper_capacity=2`, `stower_count=1`, 60-second decisions) specifically until two different fixed policies produced measurably different rewards on the same seed, confirmed across 5 seeds before building anything further on top of it.

## Baselines

Both implement a `.predict(obs) -> (action, state)` interface matching Stable-Baselines3's own policy signature, so one evaluation loop drives all three policy types identically (`backend/app/rl/baselines.py`):

- **Static baseline**: uniform weight (0.5) on every aisle, every step — genuine no-preference FIFO (see the bucketing note above).
- **Rule-based baseline**: priority = current hamper occupancy — "prioritize whichever aisle is most on fire." Not tuned, not learned, a plausible first guess a human might actually write.

## Evaluation protocol and results (ran 2026-10-31)

Trained PPO for 50,000 timesteps (≈23s wall-clock) on `rl_stow_balancing.yaml`, against one fixed world instantiation (seed 2001) — the policy's own action sampling is stochastic during training, but the underlying scenario is not resampled per episode. Evaluated all three policies (static, rule-based, PPO) on the training scenario **and** two held-out scenario variations never seen during training (`rl_stow_balancing_high_volume.yaml`: more trucks/parcels; `rl_stow_balancing_tighter_capacity.yaml`: `hamper_capacity=1`), each across 5 fixed seeds (101–105). Re-ran the full evaluation a second time and confirmed byte-identical output — the report is reproducible.

| Scenario | Policy | Reward (mean±std) | Stowed | Max jackpot backlog | Constraint violations |
|---|---|---|---|---|---|
| training | static | 25.53 ± 1.08 | 58.0 | 26.2 | 0.0 |
| training | rule-based | 26.92 ± 0.67 | 58.6 | 27.2 | 24.2 |
| training | **PPO** | **30.95 ± 0.44** | 58.0 | 27.4 | 31.4 |
| held-out: high volume | static | 40.30 ± 0.72 | 114.2 | 71.2 | 0.0 |
| held-out: high volume | rule-based | 40.47 ± 0.76 | 114.2 | 71.2 | 39.2 |
| held-out: high volume | **PPO** | **51.30 ± 1.49** | 115.6 | 72.8 | 57.0 |
| held-out: tighter capacity | static | 26.37 ± 0.80 | 58.0 | 32.0 | 0.0 |
| held-out: tighter capacity | rule-based | 26.37 ± 0.72 | 58.0 | 32.0 | 32.6 |
| held-out: tighter capacity | PPO | 26.63 ± 1.31 | 58.2 | 32.2 | 35.8 |

Full per-seed data: regenerate with `backend/scripts/run_rl_evaluation.py` (the JSON report itself is a generated artifact, gitignored like every other `data/processed/` output — not committed).

### The honest finding

**PPO achieves the highest reward in two of three scenarios — but this is not evidence that it's operationally better, and in the one scenario that stresses the problem hardest, its advantage disappears entirely.** Looking past the reward column: PPO's `jackpot backlog` (the metric that actually matters operationally) is *not* lower than the baselines' — it's the same or marginally **worse** in every single row. Its `stowed` count is statistically indistinguishable from both baselines everywhere. The reward improvement is concentrated entirely in the `mean_hamper_occupancy` shaping term, not in the metric-contract-backed terms. On `held_out_tighter_capacity` — the scenario where good aisle-prioritization should matter most — PPO's reward (26.63 ± 1.31) is within noise of the static baseline (26.37 ± 0.80); whatever it learned on the training scenario did not transfer to a harder capacity regime.

This is reported as exactly what the roadmap exit criteria demands: **not** a claim that RL is better because reward went up, but the opposite — a documented case where reward improved yet the metrics that actually matter did not, which is itself the kind of finding `docs/RL_ENVIRONMENT_SPEC.md`'s evidence discipline exists to surface rather than hide. Plausible explanations, none confirmed: (a) the occupancy-shaping term is misaligned with the actual goal and PPO is honestly optimizing exactly what it was given; (b) 50,000 timesteps against one fixed world instantiation is too little data/diversity for genuinely transferable behavior; (c) the problem as scoped (single stower, single resource queue) may be too simple for a learned policy to beat a sensible heuristic by much, if at all. Distinguishing these needs further work, not a conclusion asserted now.

High constraint-violation counts for both rule-based and PPO (vs. zero for static) are expected and correct, not concerning: both adaptive policies routinely want to deprioritize whichever aisle is currently empty, and the anti-starvation floor correctly intervenes every time — direct, repeated evidence the hard constraint is doing real work, not sitting unused.

## Design space — final status

| Dimension | Status |
|---|---|
| State representation | **Implemented** — see "State" above. Partial/local, as required. |
| Action space | **Implemented** — see "Action" above. |
| Reward design | **Implemented**, and found wanting — see "The honest finding." The metric-contract-backed terms (stow throughput, jackpot volume delta) did not dominate the outcome; the added shaping term did, in a way that didn't serve the actual goal. |
| Hard constraints | **Implemented and measured** — anti-starvation floor, `constraint_violations` counted per step, never a reward penalty. |
| Partial observability | **Implemented** — local per-aisle + pooled signals only. |
| Multi-agent coordination | Not needed — one policy, one decision point. Still open for later problems. |
| Simulation calibration | Twin's own calibration status unchanged (ADR-0006: internal consistency only, no real-world ground truth) — the RL scenario required its own empirical retuning (see above) on top of that. |
| Generalisation / robustness | **Measured, not assumed**: PPO's advantage held on a volume-shifted held-out scenario but vanished on a capacity-shifted one. |
| Reproducibility | **Verified**: identical seeds + identical policy file reproduce the evaluation report byte-for-byte. |
| Baseline comparison | **Done** — see the results table; no claim rests on training reward alone. |

## Relationship to the agentic layer

RL and agentic AI are separate but interoperable (`docs/SYSTEM_ARCHITECTURE.md` Layer 4). Milestone 6 itself did not wire the trained PPO policy into the Flow Intelligence Agent or any other agent — given the honest finding above, doing so would mean an agent citing a policy recommendation that isn't demonstrably better than a one-line heuristic.

**Milestone 7 update (2026-10-31)**: the coordination mechanism connecting the agentic and RL layers (`backend/app/security/decision_service.py`) is now built — but it deliberately still does not use the trained PPO policy. Its candidate interventions are named, fixed priority-weight vectors (plus the static/rule-based baselines), evaluated the same way the Milestone 6 report evaluates any policy (`backend/app/rl/evaluation.py`, extracted from `scripts/run_rl_evaluation.py` so both the script and the decision service run the same evaluation code, not two copies that could drift). This proves the coordination *mechanism* — formulate a decision, request simulation-based policy evaluation, run it through a policy engine, require human approval, record an observed outcome — works correctly independent of whether any one candidate is actually good. See `docs/ENGINEERING_ROADMAP.md` Milestone 7 and `docs/adr/0009-human-approval-and-governance.md`'s implementation note for the full write-up.
