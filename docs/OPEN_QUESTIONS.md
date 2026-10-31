# Open Questions Register

Status values: `unresolved` (no leaning yet), `leaning` (a tentative direction exists but isn't decided), `blocked` (needs an external input, e.g. a domain-owner sign-off).

## Domain

| Question | Why it matters | Current leaning | Status |
|---|---|---|---|
| What is the exact formula for DEA, OTD, Sort Compliance, FPY, FSAF, Timely Staged, and Route readiness? | Metrics can't move from `proposed`/`requires_validation` to `validated` without it (`docs/OPERATIONAL_DOMAIN_MODEL.md` §4) | None — must come from a domain owner or published generic industry definition, not invented | `blocked` |
| Should the synthetic reference station support more than one station profile (different aisle counts, cluster structure)? | Affects whether scenario config needs a "station profile" abstraction on top of "scenario" | Lean yes, eventually — not needed until Milestone 4's scenario format is designed | `leaning` |

## Data architecture

| Question | Why it matters | Current leaning | Status |
|---|---|---|---|
| Exact event-ingestion mechanism (outbox table vs. append-only event table vs. something else) | Determines Milestone 2's core implementation | Lean toward an append-only event table with a separate projection step, as the simplest thing that satisfies the idempotency/ordering requirements — not committed | `leaning` |
| Scenario/simulation-config file format (YAML vs. JSON vs. Python dataclass) | Blocks Milestone 4 implementation start | Lean YAML for human-editability; no ADR written yet because the stakes are low and reversible | `leaning` |
| When (if ever) does real streaming infrastructure (Kafka or similar) get introduced? | ADR-0004 defers it until justified by actual throughput/fan-out needs | Revisit when more than one consumer needs the same event stream independently, or induct-time latency requirements get strict | `unresolved` |

## Agentic AI

| Question | Why it matters | Current leaning | Status |
|---|---|---|---|
| Custom orchestration state machine vs. LangGraph — final call | ADR-0005 starts custom; revisit condition is defined there | Revisit once 2+ agents need cross-agent checkpoint/resume behavior the custom machine is clearly straining to support | `leaning` |
| Which LLM provider(s) back the production `LLMProvider` abstraction (ADR-0008)? | Needed before Milestone 5 can run anything for real | None yet — deliberately deferred past CLI-based development | `unresolved` |
| Exact memory/retrieval mechanism for past decision records | `docs/AGENTIC_ARCHITECTURE.md` §Memory sketches the shape but not the implementation | None | `unresolved` |

## Digital twin / RL

| Question | Why it matters | Current leaning | Status |
|---|---|---|---|
| Which narrow decision problem is the first RL target? | Blocked Milestone 6 design start | **Resolved 2026-10-31** by project-owner decision: aisle-level stow capacity and workload balancing under variable inbound flow (ADR-0007 amendment, `docs/RL_ENVIRONMENT_SPEC.md`). State/action/reward formalization remains open Milestone 6 work. | `resolved` |
| How is the digital twin calibrated/validated against *something* if there's no real operational data to compare against (by design, per the synthetic-data constraint)? | Affects whether "calibrated" can mean anything more than "internally consistent" | Lean toward validating internal consistency (conservation of parcels, queueing-theory sanity checks) rather than claiming real-world fidelity | `leaning` |
| Exact reward function for the first RL problem (aisle-level stow capacity/workload balancing) | Reward design is explicitly "open" in the RL spec; must be defined against `validated`/clearly-labeled `proposed` metrics only | None — unblocked now that the problem itself is chosen, but still genuine Milestone 6 design work | `unresolved` |

## Governance / security

| Question | Why it matters | Current leaning | Status |
|---|---|---|---|
| RBAC role model — what roles exist, who can approve what class of recommendation? | Needed before Layer 5 (Milestone 7) can be built | None | `unresolved` |
| Project license | Affects public-repo readiness | None — flagged in `README.md` | `unresolved` |
| Project/station branding (is "Station NOVA-1" the permanent fictional identity, or a placeholder?) | Cosmetic but referenced across docs/code once simulation starts | Treat as the working default until told otherwise | `leaning` |

## How to resolve one of these

Update the row's status and leaning in this file, and if the resolution is a significant, hard-to-reverse architectural choice, promote it to a new ADR in `docs/adr/` rather than just editing this register — this file is for tracking the unknown, not for recording the decided.
