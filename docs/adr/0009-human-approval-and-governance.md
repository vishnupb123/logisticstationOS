# ADR-0009: Human approval and governance

**Status**: Accepted

## Context

StationOS's agentic and RL layers will eventually produce recommendations (and, in RL's case, learned policies) about operational decisions. Without an explicit governance stance, there's real risk of "the agent suggested it, so the system just did it" creeping in as a convenience during implementation.

## Options considered

1. **Let sufficiently-confident agent/RL output act directly (e.g., auto-apply a recommendation above some confidence threshold).** Rejected outright: StationOS's founding brief is explicit that it must not autonomously control physical operations, employee allocation, workforce decisions, parcel handling, or dispatch, regardless of confidence. A confidence threshold is a tuning knob on an approach that's disallowed in principle, not a safer version of it.
2. **Human approval required for everything, with no differentiation by risk/reversibility.** Simpler, but likely to become either a bottleneck that gets worked around, or a rubber-stamp step that provides governance in name only.
3. **A governed pipeline — policy engine, constraint validation, risk evaluation, then role-appropriate human approval, with a permanent audit record — gating every operationally consequential recommendation, with hard constraints enforced structurally rather than as reward/confidence tuning.** Chosen.

## Decision

Every operationally consequential recommendation from the agentic layer or the RL layer passes through Layer 5 governance (`docs/SECURITY_AND_GOVERNANCE.md`) before any real-world effect: policy engine → constraint validation → risk evaluation → human approval → audit record. Safety, physical, labour, and authorisation constraints are hard constraints enforced at the environment/governance level (e.g., action masking in RL, eligibility rules in the policy engine), never expressed as something a learned policy or an agent's confidence score could override.

## Rationale

This is the project's clearest non-negotiable principle, stated multiple times in the founding brief in different words. Encoding it as an ADR makes it a structural commitment future implementation work is checked against, not a value that has to be re-derived from first principles each time a new feature is built.

## Consequences

- No feature, however convenient, may skip the approval gate for an operationally consequential action — this must be treated as a correctness bug if it happens, not an optimisation.
- Layer 5 (RBAC, policy engine, audit) must exist before any agent/RL output is wired to anything beyond simulation or read-only recommendation display (reflected in the roadmap: Milestone 7 before any "act on this" capability).
- Risk evaluation requires a notion of blast radius/reversibility per recommendation type — this needs its own design work, tracked as an open question.

## Risks

- Over-applying the approval gate to low-stakes, easily-reversible suggestions (e.g., "here's a dashboard insight") could create unnecessary friction — mitigated by scoping "operationally consequential" to actions with real-world physical/workforce/dispatch effect, not every piece of agent output.

## Revisit conditions

This governance stance is not expected to be revisited by convenience; it would only change via a deliberate, explicit decision with its own new ADR, not as a side effect of unrelated feature work.
