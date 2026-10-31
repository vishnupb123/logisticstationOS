# StationOS — Engineering Handoff

**Purpose of this file**: the persistent, single source of truth for "where StationOS actually stands," written so a new engineering session (human or AI) can continue without this conversation's history. If something here conflicts with a doc in `docs/`, the more detailed doc wins for *content*; this file wins for *current status and what to do next*.

Last updated: 2026-10-31 (Milestone 9 completed this session).

---

## 1. Current milestone status

| Milestone | Status |
|---|---|
| 1 — Software foundation | ✅ Complete |
| 2 — Domain model and event infrastructure (Cycle 1 slice) | ✅ Complete |
| 3 — Data engineering and analytics | ✅ Complete |
| 4 — Digital twin | ✅ Complete |
| 5 — Agentic AI system | ✅ Complete |
| 6 — Reinforcement-learning environment | ✅ Complete |
| 7 — Agent and RL coordination | ✅ Complete |
| 8 — Predictive intelligence | ✅ Complete |
| 9 — Governance and reliability | ✅ **Complete** (this session) |
| 10 — Operational command centre | Not started — **next, but unscoped** |

Full milestone definitions: `docs/ENGINEERING_ROADMAP.md`. **Frontend remains explicitly deferred** — carried forward from two prior sessions' handoffs. It still needs its own scoping conversation (what subset of the full view list, what minimal API layer, how RBAC should gate it) before any frontend code is written.

## 2. What was built this session (Milestone 9)

A large, multi-part milestone — `docs/ENGINEERING_ROADMAP.md` lists eight deliverables; all eight got real, proportionate treatment (some new code, two were genuine reviews with documented findings, not gaps that needed new code):

**RBAC** (`backend/app/security/rbac.py`): `Role` (`operator`/`supervisor`/`admin`), a fixed role → eligible-decision-type permission table, `check_can_approve` (raises `RBACError`). `repository.py::approve_decision`/`reject_decision` now require an `approver_role: Role` and check it before mutating anything, persisting the role alongside `approved_by` (`DecisionRecord.approver_role`, new column). Deliberately simple and code-defined — checks a role the caller *claims*, since there's no real login/session system yet for a database-backed role to attach to. **Honest remaining gap**: no verified identity behind that claim (see §6).

**Shadow-mode evaluation**: `decision_service.py::propose_decision(..., shadow=True)` creates a `DecisionRecord` with status `shadow` instead of `pending_approval` — a terminal status. No separate guard was added: the existing `_require_pending`/`APPROVED`-only checks in `repository.py` already only accept `pending_approval`/`approved` respectively, so `shadow` is excluded automatically.

**Data validation**: `repository.py::create_decision_record` now re-validates every JSONB-bound argument (evidence as `list[Finding]`, candidates as a new `policy_engine.py::CandidateRecord`, policy-engine result, risk evaluation) against its real Pydantic schema before persisting — a malformed caller gets a loud `ValidationError`, not silently-corrupt audit data.

**Model and policy versioning**: `backend/app/core/versioning.py::validate_version_format` names and checks the dated `"YYYY-MM-DD.N"` convention `POLICY_VERSION`/`MODEL_VERSION` already followed ad hoc — both now have a test asserting they match it. `DecisionRecord.component_versions` (new column) stamps every decision with the exact version of each component that produced it (currently just the policy engine).

**Secure configuration review**: `Settings.postgres_password` is now `pydantic.SecretStr`, masked out of `repr()`/`str()` by default (`postgres_dsn` explicitly unwraps it with `.get_secret_value()`). `.env.example`/`docker-compose.yml` reviewed — only placeholder values.

**Observability**: `backend/app/core/tracing.py` — a minimal, local-first OpenTelemetry integration: `SimpleSpanProcessor` + `ConsoleSpanExporter` only (deliberately not `BatchSpanProcessor` — no background export thread to leak past process/test shutdown). `AgentExecutor.run`/`resume` and `decision_service.py`'s `propose_decision`/`observe_outcome` are instrumented with spans. `get_tracer()` is safe to call anywhere (scripts, tests, app code) without `configure_tracing()` ever being invoked — the OpenTelemetry API's own no-op default handles it, so no test or script gets unrequested console span noise; only `app/main.py` opts in for real.

**Error-handling and idempotency reviews** (documented in `docs/SECURITY_AND_GOVERNANCE.md`, no new code needed): the readiness probes' broad `except Exception: return False` is deliberate and correct (best-effort health checks, not swallowed real errors); `AgentExecution`/`DecisionRecord` rows are deliberately non-idempotent — each call creates a new audit-log row, by design, since both represent *events* ("this ran," "this was proposed"), not records to deduplicate.

**Migration** `8a19c7f88922` adds `approver_role`/`component_versions` to `decision_records`, upgrade/downgrade-verified.

**23 new tests** (131 → 154 total): `tests/security/test_rbac.py` (6), `tests/core/test_versioning.py` (3), `tests/core/test_tracing.py` (2), plus RBAC/shadow/data-validation coverage added to `tests/security/test_repository.py` and `test_decision_service.py`, and a version-format check added to `tests/predictive/jackpot_risk/test_model.py`.

## 3. The exit criteria, demonstrated live

`scripts/run_decision_demo.py` now runs, against real Postgres and real simulation, in order: propose → policy engine → (refused) outcome-before-approval → **an `OPERATOR` tries to approve, refused by RBAC** → **a `SUPERVISOR` approves successfully** → observed-outcome simulation run → **a shadow-mode decision proposed, and refused approval even by an `ADMIN`**. This is the literal roadmap exit criterion ("a recommendation... cannot reach 'acted on' status without RBAC-checked human approval... shadow-mode runs produce output clearly labeled as not-executed"), exercised live, not just asserted in docs — sample real output is in `docs/SECURITY_AND_GOVERNANCE.md` and `docs/ENGINEERING_ROADMAP.md`.

## 4. Known limitations (read before building on RBAC)

- **No verified identity behind a claimed `Role`.** Anyone calling `approve_decision`/`reject_decision` can assert `Role.ADMIN` and it will be trusted. This milestone built the permission *table* and the *check*, not an authentication system — there isn't one yet, and none was pretended into existence. Don't build anything that treats `approved_by`/`approver_role` as verified identity.
- **`risk.py` is still a stub** (unchanged from Milestone 7) — every decision type is honestly `simulation_only`/reversible because nothing acts on a live system yet.
- **Tracing is local-only, single-process.** `app/core/tracing.py` correlates multi-step operations within one Python process; there's still no real network/process hop to call genuinely "distributed." Revisit a real exporter only once one exists.
- **Only one decision type's RBAC permissions are populated** (`aisle_stow_priority`) — adding a second decision type means deliberately adding it to `rbac.py`'s permission table, not something that happens automatically.
- The tests-vs-dev-database footgun from prior milestones is unchanged (hit and recovered the documented way during this session's manual testing).

## 5. Open questions

Full register: `docs/OPEN_QUESTIONS.md`. Resolved this session: RBAC role model (now `operator`/`supervisor`/`admin`). New this session: real identity/auth behind RBAC's claimed role (unresolved — real gap); real drift-monitoring/distributed-tracing beyond this milestone's minimal first cut (unresolved). Unchanged: real risk/blast-radius model beyond the Milestone 7 stub; should the jackpot-risk prediction or the trained RL policy ever be wired into an agent/decision (both still leaning: not yet); metric formulas still `requires_validation`; live `OllamaProvider` verification pending.

## 6. Security considerations

The decision-governance pipeline is now RBAC-checked end to end for the one piece that was missing after Milestone 7. The honest limitation (§4, §5) is prominent by design, not buried — a reviewer should come away knowing RBAC here means "a checked permission table," not "an authenticated system." `Settings.postgres_password` is now `SecretStr`. No new real secrets, credentials, or data introduced. The new base dependencies (`opentelemetry-api`/`opentelemetry-sdk`) are standard, widely-used packages; tracing output never includes secret values (spans only carry the attributes this code explicitly sets — decision type, candidate count, execution IDs — never `Settings` or connection strings).

## 7. Recommended next steps

**Milestone 10 (operational command centre / frontend) is next on the roadmap, but deliberately not scoped yet** — two prior sessions' handoffs already flagged this (roadmap's own non-goal: "nothing here gets built early just because 'it would be nice to see something'"; near-total absence of an HTTP API beyond `/health`). Before writing any frontend code:
1. Have the scoping conversation explicitly — what subset of Milestone 10's full view list is realistic for a first cut, what minimal API layer it needs, and how Milestone 9's RBAC should gate which views/actions.
2. Re-read `docs/ENGINEERING_ROADMAP.md` Milestone 10 and this file's own history of raising this (see prior HANDOFF.md revisions, now superseded but the reasoning holds).

If instead continuing backend-only work: Milestone 8's "build the next predictive candidate area" and Milestone 6's "domain-randomized RL training" are both legitimate, already-scoped next steps that don't require the frontend conversation first.

## 8. Exact instructions for the next session

1. Read this file in full before doing anything — especially §4's RBAC limitation, so it isn't accidentally treated as more solved than it is.
2. Confirm Milestones 1–9 still work: `cd backend && pip install -e ".[dev,analytics,rl,predictive]" && ruff check .`; bring up Postgres, `alembic upgrade head` (four migrations), `pytest -q` (154 tests). If `alembic upgrade head` silently no-ops, it's the documented tests-vs-dev-database footgun — drop `alembic_version` and retry (but check first whether the tables actually need recreating — stamping to head is the right fix if they don't, re-running from scratch if they were genuinely dropped).
3. If the project owner wants to proceed with the frontend: stop and have the scoping conversation from §7 before writing code — don't default into building it.
4. If continuing backend work instead: pick deliberately from the legitimate open items in §5, don't start a seventh predictive candidate area or a new RL problem without being asked.
5. When the next milestone is done: update this file's status table and date, run the full verification sequence from step 2 one more time and report the actual result, and update `docs/OPEN_QUESTIONS.md` for anything resolved or newly found.
