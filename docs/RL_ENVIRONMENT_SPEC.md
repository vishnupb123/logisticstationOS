# Reinforcement Learning Environment Specification

## Status: research direction, not a committed design

Everything in this document is a **starting hypothesis**, not a finished specification. Treat every subsection as `proposed`, pending the narrow-problem definition work in Milestone 6.

## Research question

> Can a hierarchical, agent-coordinated reinforcement learning architecture improve decision-making in partially observable, capacity-constrained logistics operations, compared with conventional rule-based and isolated optimisation approaches?

This is a hypothesis to investigate, not a result to assume. StationOS's RL work should be judged on whether it produces a credible, reproducible answer to this question for a narrow decision problem — not on whether it ships a production policy.

## Stack

Gymnasium (environment interface) + Stable-Baselines3 (algorithm implementations) + PyTorch (backing framework). PPO is a **candidate baseline**, not a predetermined solution — other algorithms (e.g., value-based methods, or even a well-tuned heuristic) should be evaluated if the formal problem structure suggests they fit better.

## Start narrow

The roadmap explicitly rejects "optimise the whole station" as a v1 target.

**First problem (decided 2026-10-31, see ADR-0007 amendment): aisle-level stow capacity and workload balancing under variable inbound flow.** The project owner selected this directly rather than it being derived from twin calibration, which is how ADR-0007 originally envisioned the selection happening. Naming the problem does not settle its formalization — the state/action/reward design below is still open Milestone 6 work, and if Milestone 4's calibrated twin shows the problem is mis-posed as scoped, that goes back to ADR-0007, not a silent substitution.

Two other candidates were considered during the architecture phase and are not pursued now, but are kept here in case the selected problem proves intractable and a fallback is needed:
- Stower-to-hamper allocation under jackpot pressure during induct.
- Wave-sequencing / cart-release timing during Pick & Stage.

## Candidate state/action variables (illustrative, not finalized)

Carried over from the project owner's problem framing, to ground Milestone 6 design work — none of this is committed until the state/action space is actually formalized against the calibrated twin:

- **Candidate state variables**: aisle workload, hamper occupancy, stower availability, induct throughput, jackpot backlog, remaining processing time, capacity constraints, demand uncertainty.
- **Candidate actions**: workload allocation, eligible-capacity redistribution, stow-resource allocation within permitted constraints, priority selection for eligible work.
- **Explicitly excluded from the action space**: anything that would violate physical, safety, or labour constraints — these are never offered as selectable actions, not merely discouraged via reward (see "Hard constraints" below).

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
| Baseline comparison | Not open — every trained policy is compared against (a) a static baseline (no reallocation), (b) a rule-based heuristic baseline, and (c) held-out scenario performance, using multiple seeds, before any claim of improvement. Training reward going up is never itself treated as evidence of improvement. |

## Evaluation protocol (draft)

1. Define the narrow decision problem and its metric-contract-backed reward.
2. Establish a rule-based baseline policy in the digital twin.
3. Train a candidate RL policy against the calibrated twin, across the scenario catalog, with seeded, logged runs.
4. Compare against the baseline on held-out scenario variations, not just the training scenario.
5. Report results as what they are — simulated performance under a specific environment and reward definition — never as a validated real-world outcome. No performance numbers exist yet; none should be published in this repository until step 4 has actually run.

## Relationship to the agentic layer

RL and agentic AI are **separate but interoperable** (`docs/SYSTEM_ARCHITECTURE.md` Layer 4). A trained policy's recommendation is evidence an agent can cite (tagged as a `prediction`/`recommendation`, with its evaluation protocol as supporting context) — it is not itself an agent, and an LLM is never used as a substitute for the optimisation algorithm here.
