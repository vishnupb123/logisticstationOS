# ADR-0009: Human approval and governance

**Status**: Accepted; implemented (not revisited) by Milestone 7 — see "Implementation note" below.

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

## Implementation note (2026-10-31): the governance pipeline, built

Milestone 7 implements the pipeline this ADR describes (`backend/app/security/`): `policy_engine.py` (eligibility/constraint checks, rule-based by design — a policy engine that itself needed training would be the thing it's supposed to check), `risk.py` (a minimal, explicitly-labeled stub — every decision type so far only affects the digital twin, so "blast radius" is honestly `simulation_only` and reversible by construction; a real blast-radius model per the Consequences section above is still open, tracked in `docs/OPEN_QUESTIONS.md`), `repository.py` (the approval/audit persistence, `DecisionRecord`), and `decision_service.py` (the coordination logic connecting agent evidence, RL-environment-based candidate evaluation, and the policy engine).

The structural guarantee this ADR calls for — "no path lets a recommendation become acted on without approval" — is enforced in code, not just documented: `record_observed_outcome` raises if the `DecisionRecord` isn't `APPROVED`, and `approve_decision`/`reject_decision` both raise if the record isn't still `PENDING_APPROVAL` (no re-deciding a decided record). RBAC (who is allowed to approve) remains Milestone 9 — `approved_by` today is a plain string, not a checked role, matching this ADR's own sequencing note above ("Layer 5... must exist before any agent/RL output is wired to anything beyond simulation," not "RBAC must exist first" — the approval *gate* exists now, role-checking who may use it is the remaining piece).

## Implementation note (2026-10-31): RBAC and shadow mode, built

Milestone 9 closes the gap the previous note named. `backend/app/security/rbac.py` adds `Role` (`operator`/`supervisor`/`admin`) and a fixed, auditable role → eligible-decision-type table; `repository.py::approve_decision`/`reject_decision` now call `rbac.check_can_approve` before mutating anything, and persist the approver's claimed role (`DecisionRecord.approver_role`) alongside `approved_by`. This is deliberately a role the identity *claims* and is checked against a fixed table, not backed by a real login/session system (none exists yet) — the Consequences section above already anticipated this sequencing ("Layer 5... must exist before" — RBAC is the next layer on top of the governance pipeline, not a precondition for it existing at all).

Also added: shadow-mode proposals (`DecisionRecord` status `shadow`, set by `decision_service.py::propose_decision(..., shadow=True)`) — a decision that can never be approved, rejected, or have an outcome recorded, by the same structural mechanism (every status-changing function only accepts `pending_approval` as a starting point), satisfying this milestone's "shadow-mode evaluation support, keeping recommendations visibly separate from anything executed" deliverable without adding a second parallel guard to maintain.

Real remaining gap, honestly stated: there is still no verified identity behind a claimed `Role` — anyone calling `approve_decision` can assert any role. This is a known, explicit limitation (`docs/OPEN_QUESTIONS.md`), not something this milestone claims to have solved; a real auth system would supply the verified `Role` this module already expects, without this module's own checking logic needing to change.
