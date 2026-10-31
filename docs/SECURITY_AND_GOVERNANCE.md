# Security and Governance

## Human-in-the-loop governance (the central constraint)

StationOS must not autonomously control physical operations, employee allocation, workforce decisions, parcel handling, or dispatch (ADR-0009). This applies to every layer:

- The **agentic layer** (`docs/AGENTIC_ARCHITECTURE.md`) produces recommendations, not actions.
- The **RL layer** (`docs/RL_ENVIRONMENT_SPEC.md`) enforces safety/labour/authorisation constraints as hard constraints at the environment level, not as reward penalties, and its output is evaluated in simulation, not applied live, until there is an explicit, separately-decided path to do otherwise.
- Anything operationally consequential routes through **Layer 5 governance** before it can be acted on.

## Decision governance pipeline (implemented, Milestones 7 & 9 — `backend/app/security/`)

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
Human approval  — a role-checked approver records a decision + rationale
        (repository.py::approve_decision/reject_decision — now RBAC-
         checked, rbac.py::check_can_approve, before anything is
         mutated; also re-validates every argument against its
         Pydantic schema before persisting it)
        ▼
Audit record  — decision, evidence, approver + role, component
        versions, outcome, timestamp — permanent
        (the DecisionRecord row itself, models.py)
```

**RBAC (Milestone 9)**: `backend/app/security/rbac.py` — `Role` (`operator`/`supervisor`/`admin`), a fixed, auditable table of which decision types each role may decide on (`OPERATOR` can propose/investigate but decide nothing; `SUPERVISOR` can decide on the one known decision type; `ADMIN` can decide on anything, including a decision type invented later), and `check_can_approve` (raises `RBACError`, never silently lets an unauthorized approval through). Deliberately simple and code-defined, not a database-backed permission system — there is no real user/auth system yet (no login, no session) for a database-backed role to attach to; this checks the role an identity *claims* to hold, the same "deliberately simple, not learned" precedent the policy engine set. If a real auth system arrives later, it supplies the verified `Role` this module already expects — the checking logic itself doesn't need to change.

**Shadow-mode evaluation (Milestone 9)**: a decision can be proposed with `shadow=True` (`decision_service.py::propose_decision`) — created with status `shadow`, a terminal status visibly distinct from `pending_approval` in any listing. A shadow-mode decision can never be approved, rejected, or have an outcome recorded: every status-changing function in `repository.py` only accepts a record already in `pending_approval`, so `shadow` is excluded automatically, with no separate check to maintain. Use case: evaluate a new candidate shape informationally, without it ever being eligible for real adoption.

See ADR-0009's implementation notes and `docs/ENGINEERING_ROADMAP.md` Milestones 7 and 9.

## Secrets and configuration

- No secrets, credentials, or `.env` files are committed. `.gitignore` excludes `.env*` (an `.env.example` with placeholder values, no real ones, is fine and expected).
- Configuration is sourced from environment variables via `app/core/config.py::Settings` — nowhere else in the codebase should read a credential directly.
- **Reviewed (Milestone 9)**: `Settings.postgres_password` is a `pydantic.SecretStr`, not a plain `str` — masked out of `repr()`/`str()`/any accidental log by default; `postgres_dsn` explicitly calls `.get_secret_value()` to build the real connection string. This makes "never log a full `Settings` object" true even if something does by accident, rather than relying only on the convention. No other current setting (Ollama base URL/model, DuckDB path) is a secret. `.env.example` and `docker-compose.yml` were reviewed and contain only placeholder values (`stationos`/`stationos`), consistent with the public-repository checklist below.
- If Snowflake or other external tooling is detected on a developer's machine, StationOS code may check *whether* relevant environment variables are set (by name only) but must never assume valid account access, read a credential value into a log, or attempt a connection without the user's explicit configuration.

## Reliability reviews (Milestone 9)

Two deliverables from `docs/ENGINEERING_ROADMAP.md` Milestone 9 were genuine reviews, not just new code — the conclusion in both cases is "the existing pattern is correct, documented here rather than silently assumed":

- **Error handling and retry policy**: `app/db/postgres.py::check_connection` and `app/db/duckdb.py::check_connection` each catch a broad `Exception` and return `False` — reviewed and confirmed correct: these are best-effort readiness probes (`/health/ready`), and propagating a raw connection exception to a health-check caller would be strictly worse than a clean boolean. `AgentExecutor`'s bounded retry (Milestone 5, `app/orchestration/runner.py`) remains the one real retry policy in the codebase, scoped to the one failure mode that's actually transient (an LLM provider call) — reviewed and confirmed no other code path (simulation runs, RL/predictive training, decision coordination) does anything non-deterministic or network-dependent that would benefit from a retry; adding one anywhere else would be retrying a bug, not a flake.
- **Idempotency**: the event store (Milestone 2, `app/events/store.py`) is the one place idempotency is load-bearing — a duplicate `idempotency_key` is silently and correctly a no-op (`ON CONFLICT DO NOTHING`). `AgentExecution` rows (Milestone 5) and `DecisionRecord` rows (Milestone 7) are deliberately **not** idempotent — each call creates a new row, by design: both are audit logs of *events* ("this agent ran," "this decision was proposed"), not records to be deduplicated. Calling `propose_decision` twice with identical inputs is expected to produce two decision records, not collapse into one; a human reviewing them can reject the duplicate. Reviewed and confirmed: no gap found that needed fixing.

## Model and policy versioning (Milestone 9)

`backend/app/core/versioning.py::validate_version_format` names and checks the dated `"YYYY-MM-DD.N"` convention `app/security/policy_engine.py::POLICY_VERSION` and `app/predictive/jackpot_risk/model.py::MODEL_VERSION` already followed ad hoc before this module existed — both now have a test asserting they actually match it. `DecisionRecord.component_versions` (Milestone 9) stamps every decision with the exact version of each component that produced it (currently just the policy engine; a future decision type that also uses a predictive model's output would add its version there too) — a real answer to "which version of which component produced this," not just a single field nobody checks.

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
| Unauthorized approval of a governed recommendation | The approval gate exists and is now RBAC-checked (Milestone 9 — `approve_decision`/`reject_decision` call `rbac.check_can_approve` before mutating anything); still no real auth system behind the claimed `Role` (no login/session) — that's a real remaining gap, tracked in `docs/OPEN_QUESTIONS.md` |
| Malformed data entering the permanent audit record | `app/security/repository.py::create_decision_record` re-validates every JSONB-bound argument (evidence, candidates, policy-engine result, risk evaluation) against its real Pydantic schema before persisting — a structurally invalid caller gets a loud `ValidationError`, not silently-corrupt audit data (Milestone 9) |
| Secret leakage via logs | `Settings.postgres_password` is a `pydantic.SecretStr` (Milestone 9), masked out of `repr()`/`str()` by default; structured logging (`structlog`) should still never log a full `Settings` object or raw connection string regardless; log field allow-listing is a Milestone 2 follow-up once there's more to log |
| Dependency supply-chain risk | Dependencies pinned with version ranges in `pyproject.toml`; no unreviewed packages added without checking they're from a reputable source |

This threat model will grow as each layer gets built — it is not meant to be complete at the foundation phase, only to establish that security is considered per-layer from the start rather than bolted on later.
