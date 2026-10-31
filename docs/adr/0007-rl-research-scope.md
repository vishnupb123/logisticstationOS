# ADR-0007: Reinforcement-learning research scope

**Status**: Accepted; amended 2026-10-31 — first problem selected and (separately) implemented/evaluated (see §"Amendment" and §"Implementation note" below)

## Context

StationOS's vision includes RL-based decision-policy learning for capacity-constrained logistics operations. Left unscoped, this invites attempting to "optimise the whole station" — a research project, not an engineering milestone — before even one narrow problem has been solved credibly.

## Options considered

1. **Optimise the full station (all decisions, all cycles) with a single RL system.** Rejected: the state/action space is enormous, the reward structure would conflate many different operational concerns, and there is no way to evaluate "did this work" credibly without an unrealistic amount of twin calibration first.
2. **Skip RL entirely until the rest of the platform matures.** Rejected: RL is explicitly part of the product vision and research direction; deferring it indefinitely abandons the stated goal rather than scoping it responsibly.
3. **Start with one narrow, well-defined, bounded decision problem, validated against a calibrated digital twin, with hard safety/labour/authorisation constraints enforced outside the reward function.** Chosen.

## Decision

StationOS's RL work begins with exactly one narrow decision problem (to be selected per `docs/OPEN_QUESTIONS.md`, from candidates in `docs/RL_ENVIRONMENT_SPEC.md`), using Gymnasium + Stable-Baselines3 + PyTorch, with PPO as a candidate baseline (not a mandated solution), evaluated against a rule-based baseline on held-out scenarios. The research question itself ("can a hierarchical, agent-coordinated RL architecture improve decision-making...") is treated as a hypothesis to investigate, not a conclusion to design toward.

## Rationale

A narrow, falsifiable first result is more valuable — and more honest — than a sprawling attempt at full-station optimisation that can't be credibly evaluated. This also directly supports the project's "evidence-based intelligence" principle: a prediction/recommendation from an RL policy must be traceable to an evaluation protocol that actually ran, not asserted.

## Consequences

- Milestone 6 cannot start until the digital twin (Milestone 4) is calibrated — RL quality is bounded by simulation quality.
- Safety, physical, labour, and authorisation constraints are implemented as hard constraints (e.g., action masking) at the environment level, not reward penalties — this is non-negotiable per ADR-0009's governance stance, not merely a modelling choice to revisit.
- No RL performance claim is published without a baseline comparison on held-out scenarios actually having run.

## Risks

- A narrow first problem may not demonstrate the full hierarchical multi-agent coordination the research question is ultimately about — accepted, since a credible narrow result is a precondition for a credible broader claim, not a substitute for one.

## Revisit conditions

Revisit scope expansion only after the first narrow problem has a credible, reproducible evaluation report.

## Amendment (2026-10-31): first problem selected

The project owner designated the first narrow decision problem directly, in the implementation-phase handoff, rather than it being derived here against a calibrated twin as originally envisioned in the Decision above: **aisle-level stow capacity and workload balancing under variable inbound flow.**

This resolves the "which narrow problem" row in `docs/OPEN_QUESTIONS.md` as a project-owner decision, not an engineering derivation — the original caution in this ADR (resolve against the calibrated twin, not in the abstract) still applies to *how the problem is formalized* (exact state/action/reward, per `docs/RL_ENVIRONMENT_SPEC.md`), which remains Milestone 6 design work and is not settled by naming the problem now. If Milestone 4's calibrated twin reveals this problem isn't tractable or well-posed as scoped, that's a finding to bring back to this ADR, not a reason to silently substitute a different problem without updating this record.

## Implementation note (2026-10-31): formalized, implemented, evaluated — with a cautionary result

Milestone 6 built the environment (`backend/app/rl/env.py`), trained PPO against it, and ran the required baseline comparison across multiple seeds and two held-out scenario variations (full results: `docs/RL_ENVIRONMENT_SPEC.md` §"Evaluation protocol and results"). Consistent with this ADR's own Consequences ("no RL performance claim is published without a baseline comparison... actually having run"), the result is reported exactly as it came out, not smoothed into a success story: **PPO's reward was higher than both baselines in two of three scenarios, but its jackpot-backlog outcome — the metric that actually matters — was the same or marginally worse than the baselines' in every scenario, and its reward advantage vanished entirely on the hardest held-out variation.** The likely culprit is the reward's own shaping term (mean hamper occupancy), which dominated the outcome over the two metric-contract-backed terms (stow throughput, jackpot volume delta) — a reward-design lesson, not a verdict on RL as an approach.

This is treated as a genuine, useful first result for a narrow, falsifiable research direction (per this ADR's Rationale) — not a failure to hide and not grounds to quietly try a different reward until the numbers look better. Revisiting the reward design, or training on randomized rather than single-fixed-world instantiations, is tracked in `docs/OPEN_QUESTIONS.md` as real follow-up work.

