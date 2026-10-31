# Reinforcement Learning Environment Specification

## Status: research direction, not a committed design

Everything in this document is a **starting hypothesis**, not a finished specification. Treat every subsection as `proposed`, pending the narrow-problem definition work in Milestone 6.

## Research question

> Can a hierarchical, agent-coordinated reinforcement learning architecture improve decision-making in partially observable, capacity-constrained logistics operations, compared with conventional rule-based and isolated optimisation approaches?

This is a hypothesis to investigate, not a result to assume. StationOS's RL work should be judged on whether it produces a credible, reproducible answer to this question for a narrow decision problem — not on whether it ships a production policy.

## Stack

Gymnasium (environment interface) + Stable-Baselines3 (algorithm implementations) + PyTorch (backing framework). PPO is a **candidate baseline**, not a predetermined solution — other algorithms (e.g., value-based methods, or even a well-tuned heuristic) should be evaluated if the formal problem structure suggests they fit better.

## Start narrow

The roadmap explicitly rejects "optimise the whole station" as a v1 target. A defensible starting decision problem is scoped to one bounded choice with a clear reward signal and a feasible state space — for example (illustrative candidates, **not decided**):

- Stower-to-hamper allocation under jackpot pressure during induct.
- Wave-sequencing / cart-release timing during Pick & Stage.

Selecting the actual first problem is an open question (`docs/OPEN_QUESTIONS.md`) to resolve against the calibrated digital twin, not in the abstract.

## Design space (open, not finalized)

| Dimension | Status |
|---|---|
| State representation | Open — must reflect partial observability honestly (an agent/policy shouldn't see global station state if the real decision-maker wouldn't) |
| Action space | Open — depends on chosen decision problem |
| Reward design | Open — must be defined in terms of the metric contracts in `docs/OPERATIONAL_DOMAIN_MODEL.md` §4, using only `validated` or clearly-labeled `proposed` metrics, never an invented proxy presented as authoritative |
| Hard constraints | **Not open** — safety, physical capacity, labour policy, and authorisation requirements are enforced as hard constraints (e.g., action masking) at the environment level, never as reward penalties a policy could learn to trade off against. This is a governance requirement (ADR-0009), not a modelling preference. |
| Partial observability | Open — likely POMDP framing given real supervisors don't have global visibility either |
| Multi-agent coordination | Open — whether the first problem needs more than one learning agent, or whether that's a later extension |
| Simulation calibration | Depends on `docs/DIGITAL_TWIN_SPEC.md` reaching a validated baseline first |
| Generalisation / robustness | Open — evaluate across the scenario catalog, not just the scenario trained on |
| Reproducibility | Not open — seeded runs, versioned configs, logged exactly as in the digital twin (`docs/DIGITAL_TWIN_SPEC.md` §"Reproducibility") |
| Baseline comparison | Not open — every trained policy is compared against (a) a rule-based heuristic and (b) current simulated "do nothing differently" behaviour, before any claim of improvement |

## Evaluation protocol (draft)

1. Define the narrow decision problem and its metric-contract-backed reward.
2. Establish a rule-based baseline policy in the digital twin.
3. Train a candidate RL policy against the calibrated twin, across the scenario catalog, with seeded, logged runs.
4. Compare against the baseline on held-out scenario variations, not just the training scenario.
5. Report results as what they are — simulated performance under a specific environment and reward definition — never as a validated real-world outcome. No performance numbers exist yet; none should be published in this repository until step 4 has actually run.

## Relationship to the agentic layer

RL and agentic AI are **separate but interoperable** (`docs/SYSTEM_ARCHITECTURE.md` Layer 4). A trained policy's recommendation is evidence an agent can cite (tagged as a `prediction`/`recommendation`, with its evaluation protocol as supporting context) — it is not itself an agent, and an LLM is never used as a substitute for the optimisation algorithm here.
