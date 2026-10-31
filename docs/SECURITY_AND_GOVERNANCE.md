# Security and Governance

## Human-in-the-loop governance (the central constraint)

StationOS must not autonomously control physical operations, employee allocation, workforce decisions, parcel handling, or dispatch (ADR-0009). This applies to every layer:

- The **agentic layer** (`docs/AGENTIC_ARCHITECTURE.md`) produces recommendations, not actions.
- The **RL layer** (`docs/RL_ENVIRONMENT_SPEC.md`) enforces safety/labour/authorisation constraints as hard constraints at the environment level, not as reward penalties, and its output is evaluated in simulation, not applied live, until there is an explicit, separately-decided path to do otherwise.
- Anything operationally consequential routes through **Layer 5 governance** before it can be acted on.

## Decision governance pipeline (implemented, Milestone 7 — `backend/app/security/`)

```
Recommendation (from agent or RL policy, with evidence + category tags)
        │
        ▼
Policy engine  — is this type of action even eligible for this pathway?
        (policy_engine.py — rule-based allow-list + constraint re-check)
        ▼
Constraint validation  — hard constraints (safety, capacity, labour, authorisation)
        (policy_engine.py, same pass — plus the RL environment's own
         structural enforcement, e.g. the anti-starvation floor)
        ▼
Risk evaluation  — what's the blast radius / reversibility of acting on this?
        (risk.py — currently a minimal, honestly-labeled stub: every
         decision type so far is simulation-only and reversible by
         construction; a real blast-radius model is still open)
        ▼
Human approval  — a named approver records a decision + rationale
        (repository.py::approve_decision/reject_decision — role-
         appropriate reviewer is NOT yet enforced: approved_by is a
         plain string today, RBAC is Milestone 9, not this stage)
        ▼
Audit record  — decision, evidence, approver, outcome, timestamp — permanent
        (the DecisionRecord row itself, models.py)
```

Role-based permissions determine who can *approve* which class of recommendation; that check is not implemented yet (`backend/app/security/` has the pipeline above but no RBAC — Milestone 9) but every upstream layer should assume it exists and route accordingly rather than exposing a "just do it" path. See ADR-0009's implementation note and `docs/ENGINEERING_ROADMAP.md` Milestone 7.

## Secrets and configuration

- No secrets, credentials, or `.env` files are committed. `.gitignore` excludes `.env*` (an `.env.example` with placeholder values, no real ones, is fine and expected).
- Configuration is sourced from environment variables via `app/core/config.py::Settings` — nowhere else in the codebase should read a credential directly.
- If Snowflake or other external tooling is detected on a developer's machine, StationOS code may check *whether* relevant environment variables are set (by name only) but must never assume valid account access, read a credential value into a log, or attempt a connection without the user's explicit configuration.

## Public repository safety

StationOS is intended to become a public GitHub project. Before any commit:

- [ ] No real company operational data, employee data, or customer data of any kind.
- [ ] No actual tracking IDs — all parcel/tracking identifiers are synthetic.
- [ ] No internal screenshots or proprietary documentation.
- [ ] No proprietary source code copied from elsewhere.
- [ ] No credentials, access tokens, or secrets (check `.env`-like files and any pasted config before staging).
- [ ] No claim that StationOS integrates with, or is endorsed by, any real operator's systems.
- [ ] Station identity and scenarios remain fictional ("Station NOVA-1" or equivalent).

This checklist is intentionally mirrored in `README.md` and `CLAUDE.md` so it's visible both to human contributors and to AI assistants working in the repo.

## Threat model (initial, non-exhaustive)

| Concern | Mitigation direction |
|---|---|
| Prompt injection via tool/data output reaching an agent | Agent tool outputs are typed and schema-validated, not raw text an LLM call blindly trusts as instructions (`docs/AGENTIC_ARCHITECTURE.md`) |
| Data integrity (bad/duplicate/out-of-order events corrupting state) | Event schema conventions — idempotency keys, explicit ordering by `occurred_at` (`docs/DATA_ARCHITECTURE.md`) |
| Unauthorized approval of a governed recommendation | The approval gate itself exists (Milestone 7 — `approve_decision`/`reject_decision`); role-based permissions on *who* may use it are not yet implemented — Milestone 9 |
| Secret leakage via logs | Structured logging (`structlog`) should never log full `Settings` objects or raw connection strings; log field allow-listing is a Milestone 2 follow-up once there's more to log |
| Dependency supply-chain risk | Dependencies pinned with version ranges in `pyproject.toml`; no unreviewed packages added without checking they're from a reputable source |

This threat model will grow as each layer gets built — it is not meant to be complete at the foundation phase, only to establish that security is considered per-layer from the start rather than bolted on later.
