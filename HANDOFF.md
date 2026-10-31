# StationOS — Engineering Handoff

**Purpose of this file**: the persistent, single source of truth for "where StationOS actually stands," written so a new engineering session (human or AI) can continue without this conversation's history. If something here conflicts with a doc in `docs/`, the more detailed doc wins for *content*; this file wins for *current status and what to do next*.

Last updated: 2026-10-31 (Milestone 6 completed this session).

---

## 1. Current milestone status

| Milestone | Status |
|---|---|
| 1 — Software foundation | ✅ Complete |
| 2 — Domain model and event infrastructure (Cycle 1 slice) | ✅ Complete |
| 3 — Data engineering and analytics | ✅ Complete |
| 4 — Digital twin | ✅ Complete |
| 5 — Agentic AI system | ✅ Complete |
| 6 — Reinforcement-learning environment | ✅ **Complete** (this session) |
| 7 — Agent and RL coordination | Not started — **next** |
| 8–10 | Not started |

Full milestone definitions: `docs/ENGINEERING_ROADMAP.md`.

## 2. What was built this session (Milestone 6)

**Dependencies**: a new `rl` extra in `backend/pyproject.toml` (`gymnasium`, `stable-baselines3`, `torch`) — deliberately *not* a base dependency, since most of the app never touches RL. Installed/verified versions: gymnasium 1.0.0, stable-baselines3 2.9.2, torch 2.15.0.

**`app/simulation/model.py` refactor** (backward compatible — all 16 existing Milestone 4 simulation tests pass unchanged): added a `StowPriorityProvider` protocol and a default no-op implementation; `stower_pool` changed from a plain `simpy.Resource` to a `simpy.PriorityResource`, with each stow request's priority now sourced from `ctx.stow_priority_provider`; extracted a new public `setup_simulation(config, *, stow_priority_provider=None)` that builds the environment and context without running it, so an RL environment can step the simulation incrementally instead of only running it to completion; added a small `aisle_codes_for(config)` helper.

**`app/rl/` — the RL environment** (per ADR-0007's amendment, naming "aisle-level stow capacity and workload balancing under variable inbound flow" as the first problem):
- `env.py`: `AisleStowPriorityController` converts a per-aisle action vector into SimPy priorities by **bucketing into 10 discrete levels**, not a full ranking — see §4 for why this mattered. It also enforces a hard anti-starvation floor (`MIN_PRIORITY_WEIGHT = 0.05`; no aisle's priority weight can ever reach literal zero), structurally in the environment, not as a reward penalty, per ADR-0007/ADR-0009. `StowBalancingEnv(gymnasium.Env)`: `Box` action space (one priority weight per aisle), `Box` observation space (per-aisle hamper occupancy, stower utilization, normalized jackpot backlog, episode time fraction), `step()` advances the simulation by a fixed decision interval (60s) and returns reward = `stowed_count - 0.5*max(backlog_delta, 0) - 1.0*mean_hamper_occupancy`.
- `baselines.py`: `StaticBaselinePolicy` (uniform weights) and `RuleBasedPolicy` (priority = current occupancy), both exposing SB3's `.predict()` interface so they drop into the same evaluation harness as a trained PPO policy.
- `scripts/train_rl_policy.py` / `scripts/run_rl_evaluation.py`: CLIs to train a PPO policy against a scenario and to evaluate static/rule-based/PPO across multiple seeds and scenarios, writing an aggregated JSON report.
- Scenarios: `simulation/scenarios/rl_stow_balancing.yaml` (training), plus two held-out variants never used in training — `rl_stow_balancing_high_volume.yaml` (more trucks/parcels) and `rl_stow_balancing_tighter_capacity.yaml` (tighter hamper capacity).

**12 new RL tests + 3 baseline tests** (79 → 91 total): environment space/determinism/termination tests, the shipped scenario actually loading, and specific tests for the priority controller's true-tie bucketing, differentiated priorities, and the anti-starvation floor (including that it doesn't clip when already at the floor).

## 3. The required evaluation, run for real

Per ADR-0007 ("no RL performance claim is published without a baseline comparison on held-out scenarios actually having run"): trained PPO for 50,000 timesteps (~23–47s wall-clock) against the training scenario, then evaluated all three policies across 5 seeds on the training scenario *and* both held-out scenarios. Re-ran the evaluation a second time and confirmed byte-identical JSON output (reproducibility check).

| Scenario | Policy | Reward | Stowed | Max jackpot backlog | Constraint violations |
|---|---|---|---|---|---|
| training | static | 25.53 ± 1.08 | 58.0 | 26.2 | 0.0 |
| training | rule-based | 26.92 ± 0.67 | 58.6 | 27.2 | 24.2 |
| training | PPO | **30.95 ± 0.44** | 58.0 | 27.4 | 31.4 |
| high_volume (held out) | static | 40.30 ± 0.72 | 114.2 | 71.2 | 0.0 |
| high_volume (held out) | rule-based | 40.47 ± 0.76 | 114.2 | 71.2 | 39.2 |
| high_volume (held out) | PPO | **51.30 ± 1.49** | 115.6 | 72.8 | 57.0 |
| tighter_capacity (held out) | static | 26.37 ± 0.80 | 58.0 | 32.0 | 0.0 |
| tighter_capacity (held out) | rule-based | 26.37 ± 0.72 | 58.0 | 32.0 | 32.6 |
| tighter_capacity (held out) | PPO | 26.63 ± 1.31 | 58.2 | 32.2 | 35.8 |

Full results and methodology: `docs/RL_ENVIRONMENT_SPEC.md` §"Evaluation protocol and results".

## 4. Two real bugs found and fixed

1. **Argsort-ranking bug.** The first `AisleStowPriorityController` implementation converted action weights to priorities via a full `argsort`-based ranking. Full argsort never produces true ties, so a "uniform" action vector was *not* equivalent to FIFO (SimPy's own tie-break) — it silently imposed an arbitrary ordering. Fixed by bucketing weights into 10 discrete priority levels so equal/near-equal weights collapse to the same priority value, restoring genuine FIFO behavior under a uniform action.
2. **Scenario-tuning bug.** The first scenario attempt (`hamper_capacity=4`, `stower_count=2`, 300s decision interval) never actually created contention: static and rule-based policies produced byte-identical trajectories, because total stow throughput was capacity-bound regardless of service order — reordering a queue that's never actually binding changes nothing. Found by directly diffing the two policies' trajectories, not assumed. Retuned to `hamper_capacity=2`, `stower_count=1`, 60s decision interval, and re-verified across 5 seeds that the policies genuinely diverge before building training/evaluation on top of it. **Lesson for next time**: a scenario config "looking" tight is not evidence it creates contention — verify empirically before trusting it.

## 5. The honest finding (read this before using the trained policy for anything)

PPO achieved the highest reward in 2 of 3 evaluated scenarios, but its **jackpot-backlog outcome — the metric that actually matters** — was the same or marginally worse than both baselines' in *every* scenario, and PPO's reward advantage vanished entirely on the hardest held-out scenario (`tighter_capacity`). The likely cause: the reward's `mean_hamper_occupancy` shaping term (an added proxy, not a metric-contract value) dominated the outcome over the two metric-contract-backed terms (stow throughput, jackpot volume delta) that the reward was meant to serve. This is reported as a genuine first result for a narrow, falsifiable research direction — not smoothed into a success story, and not a verdict on RL as an approach. See ADR-0007's "Implementation note" amendment and `docs/RL_ENVIRONMENT_SPEC.md`'s "The honest finding" section for the full write-up.

**The trained policy is not wired into any agent.** Given this result, doing so now would overstate its value (`docs/OPEN_QUESTIONS.md` tracks this explicitly as "leaning: not yet").

## 6. Known limitations

- The reward function as designed is not yet aligned with the metric that matters (jackpot backlog) — revisit the weighting, or drop the occupancy-shaping term for a sparser but more aligned signal, before training again. Tracked in `docs/OPEN_QUESTIONS.md`.
- PPO was trained against one fixed world instantiation (same scenario seed every training episode). Domain randomization (varying seeds/parameters during training) is a standard fix for exactly the generalization failure seen on `tighter_capacity`, and hasn't been tried yet. Tracked in `docs/OPEN_QUESTIONS.md`.
- Only one decision problem is formalized; the roster of other candidate RL problems in `docs/RL_ENVIRONMENT_SPEC.md` remains unbuilt by design (ADR-0007: one narrow problem at a time).
- `OllamaProvider` live-verification gap from Milestone 5 is unchanged (still not exercised against a real Ollama server).
- The tests-vs-dev-database isolation gotcha from Milestone 2 is unchanged (not hit this session's RL work specifically, since RL tests need no database — only resurfaced in the usual manual-dev-then-pytest sequence).

## 7. Open questions

Full register: `docs/OPEN_QUESTIONS.md`. Resolved this session: which narrow RL problem (already resolved prior session) was formalized, implemented, and evaluated — reward design is explicitly *not* resolved (leaning: revisit the weighting). New this session: does domain-randomized training generalize better (unresolved); should the trained PPO policy ever be wired into an agent as evidence (leaning: not yet). Unchanged and highest-priority: metric formulas still `requires_validation`; the dbt/`event_types.py` manual-sync gap; live `OllamaProvider` verification pending.

## 8. Security considerations

No change to governance stance. The anti-starvation floor in `AisleStowPriorityController` (`MIN_PRIORITY_WEIGHT`) is a concrete, structural instance of ADR-0009's "hard constraints at the environment level, not reward penalties" stance — a policy's action can shift priority but can never fully starve an aisle, regardless of what the reward function happens to reward. The RL environment still runs entirely offline against the digital twin (never against live operational state, never against PostgreSQL) — same ADR-0006 boundary the digital twin itself observes. No new secrets, credentials, or real data introduced.

## 9. Recommended next milestone

**Milestone 7 — Agent and RL coordination** (`docs/ENGINEERING_ROADMAP.md`): bring the Milestone 5 agentic layer and the Milestone 6 RL layer into the same typed-interface coordination model described in `docs/SYSTEM_ARCHITECTURE.md` Layer 4 ("an RL policy is never given authority an agent's evidence pipeline hasn't governed"). Given §5's honest finding, this is **not** "wire PPO's recommendations into the Flow Intelligence Agent" — the current policy isn't demonstrably better than the rule-based baseline on the metric that matters. Treat Milestone 7 as building the coordination *mechanism and governance path*, independent of whether any specific trained policy is good enough yet to flow through it.

## 10. Exact instructions for the next session

1. Read this file, then `docs/ENGINEERING_ROADMAP.md` Milestone 7, then `docs/SYSTEM_ARCHITECTURE.md` Layer 4, `docs/AGENTIC_ARCHITECTURE.md`, and `docs/RL_ENVIRONMENT_SPEC.md`'s "Relationship to the agentic layer" section.
2. Confirm Milestones 1–6 still work: `cd backend && pip install -e ".[dev,analytics,rl]" && ruff check .`; bring up Postgres, `alembic upgrade head` (two migrations), `pytest -q` (91 tests). RL tests need no database or dbt.
3. Before building anything that lets an RL policy's output influence an agent's findings, re-read §5 of this file — the current trained policy's result is a cautionary one, not a positive one. If Milestone 7 needs *a* policy to demonstrate coordination with, either revisit the reward design first (tracked in `docs/OPEN_QUESTIONS.md`) or be explicit that the coordination mechanism is being demonstrated independent of policy quality.
4. Don't jump ahead of the roadmap (CLAUDE.md hard rule 4) — Milestone 7 is "agent and RL coordination," not predictive intelligence (Milestone 8) or governance (Milestone 9).
5. If a live Ollama server becomes available, closing that open-question gap is a good opportunistic side task, not required for Milestone 7.
6. When Milestone 7 is done: update this file's status table and date, run the full verification sequence from step 2 one more time and report the actual result, and update `docs/OPEN_QUESTIONS.md` for anything resolved or newly found.
