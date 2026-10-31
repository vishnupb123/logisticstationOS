# ADR-0007: Reinforcement-learning research scope

**Status**: Accepted (scope-limiting decision; specific problem choice remains open)

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
