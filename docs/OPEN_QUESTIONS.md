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
| Exact event-ingestion mechanism (outbox table vs. append-only event table vs. something else) | Determined Milestone 2's core implementation | **Resolved 2026-10-31**: a single append-only `events` table (`backend/app/events/models.py`) with a replay-based projector (`backend/app/services/event_ingestion.py`) rebuilding current state from each entity's full event history on every write. See `docs/DATA_ARCHITECTURE.md` §"Event schema conventions". | `resolved` |
| Scenario/simulation-config file format (YAML vs. JSON vs. Python dataclass) | Blocks Milestone 4 implementation start | Lean YAML for human-editability; no ADR written yet because the stakes are low and reversible | `leaning` |
| When (if ever) does real streaming infrastructure (Kafka or similar) get introduced? | ADR-0004 defers it until justified by actual throughput/fan-out needs | Revisit when more than one consumer needs the same event stream independently, or induct-time latency requirements get strict | `unresolved` |
| Tests and local dev currently share one Postgres database/volume | Found in Milestone 2: pytest's schema fixture does `Base.metadata.create_all`/`drop_all` directly, independent of Alembic's own `alembic_version` bookkeeping table — running tests against the same database used for manual dev work (e.g. via `scripts/generate_synthetic_events.py --seed-db`) leaves Alembic's version table pointing at a revision whose tables pytest just dropped, so `alembic upgrade head` silently no-ops until `alembic_version` is manually cleared. Not a correctness bug in application code, but a real local-dev footgun. CI avoids it by ordering seed/export/dbt steps before pytest, not after. | Lean toward a separate `stationos_test` database (a second env-driven setting) once this starts actually costing someone time — low urgency while it's one developer on one machine who now knows about it | `unresolved` |
| `backend/analytics/models/cleaned/_cleaned__models.yml`'s `accepted_values` test on `event_type` must be kept in sync by hand with `backend/app/events/event_types.py` | A new event type added to the application without updating the dbt test either silently isn't tested or (more likely) makes `dbt test` fail on real data that's actually fine — either way it's a manual step easy to forget | Lean toward generating the dbt test's value list from `event_types.py` once there's a second or third event type added (Cycle 2, Milestone 2b+) and the manual-sync cost is felt for real, rather than building a generator for a 7-item list now | `unresolved` |

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
