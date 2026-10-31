# CLAUDE.md

Instructions for AI coding assistants (Claude Code and others) working in this repository. Read [`HANDOFF.md`](HANDOFF.md) first for current state; this file is about *how* to work here, not *what* has been decided.

## What this project is

StationOS is a local-first logistics operations intelligence platform. Milestones 1–3 (software foundation; Cycle-1 domain model and event infrastructure; data engineering and analytics) are complete; Milestone 4 (digital twin) is next. Full context: `docs/PRODUCT_VISION.md`, `docs/OPERATIONAL_DOMAIN_MODEL.md`, `docs/SYSTEM_ARCHITECTURE.md`, `docs/ENGINEERING_ROADMAP.md`, and `docs/adr/`.

## Hard rules

1. **Never introduce real operational data.** All parcel IDs, employee names, customer data, screenshots, or proprietary schemas are forbidden — synthetic data only. See `docs/SECURITY_AND_GOVERNANCE.md` §"Public repository safety". If asked to add real data, decline and explain why.
2. **Never invent proprietary metric formulas.** Metrics like DEA, OTD, FPY, FSAF are defined in `docs/OPERATIONAL_DOMAIN_MODEL.md` with status `requires_validation` where the exact calculation is unknown. Do not fill in a numerator/denominator you weren't given — propose it as a draft explicitly marked `proposed`, not `validated`.
3. **No autonomous control of physical operations, workforce, or dispatch.** StationOS is a decision-support system (see ADR-0009). Anything that would take an operationally consequential action must route through a human-approval gate, not execute directly.
4. **Don't jump ahead of the roadmap.** `docs/ENGINEERING_ROADMAP.md` defines ten sequenced milestones (foundation → domain/events → analytics → digital twin → agents → RL → agent/RL coordination → predictive intelligence → governance → frontend). If asked to build something from a later milestone, flag the dependency rather than silently scaffolding it out of order. Don't attempt more than one milestone per session.
5. **No premature infrastructure.** No Kafka until an actual streaming requirement justifies it (ADR-0004). No microservices split (ADR stack assumes a modular monolith) unless a new ADR revisits that. No mandatory cloud service (Snowflake, managed Postgres, etc.) for foundational workflows — see ADR-0001 and ADR-0010.
6. **LLM-provider independence.** Application code must go through the provider abstraction described in ADR-0008, not call a specific vendor SDK directly from agent/business logic.

## Conventions

- **Backend**: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, structlog. Linting via `ruff` (config in `backend/pyproject.toml`). Tests via `pytest` under `backend/tests/`.
- **Modular monolith**: one deployable backend, strict internal module boundaries (`domain`, `events`, `repositories`, `services`, `api`, `orchestration`, `agents`, `rl`, `simulation`, `analytics`, `security`) per `docs/SYSTEM_ARCHITECTURE.md`. A module only imports from layers below it in that architecture doc, never sideways into another vertical's internals.
- **Config**: all configuration via environment variables / `.env` through `app/core/config.py::Settings`. Never hardcode credentials or connection strings elsewhere.
- **Events**: every domain event needs `event_id`, `idempotency_key`, `correlation_id`, `schema_version`, `occurred_at`, `provenance`, and `source_kind`, per `docs/DATA_ARCHITECTURE.md`. There is one append-only `events` table (`app/events/models.py`), not one table per event type — don't add a second events table for a new event type, add a payload schema to `app/events/schemas.py::EVENT_PAYLOAD_SCHEMAS` instead.
- **Current state is a projection, never written directly.** A `Parcel`/`Truck` row's mutable fields (`lifecycle_state`, `classification`, `current_aisle_id`, `bag_id`, `status`, ...) are rebuilt by replaying that entity's event history (`app/services/event_ingestion.py`) — don't set them by hand anywhere else, even for a quick fix. If the projection logic is wrong, fix the projector, not the symptom at a call site.
- **An event with a missing or wrong predecessor is still persisted and still projected from** — flag `lifecycle_consistent = False` with a note, never silently drop a real event or pretend the sequence was fine.
- **Evidence labeling**: anything an agent emits must be tagged as one of `observation | calculated | inferred | hypothesis | prediction | recommendation` per `docs/AGENTIC_ARCHITECTURE.md`. Never present an inference or prediction as an observed fact.
- **ADRs**: a significant, hard-to-reverse architectural decision gets a new file in `docs/adr/` (format: `NNNN-title.md`, copy the structure of an existing one) before — not after — it's implemented. A roadmap-detail refinement or an implementation choice within an already-accepted ADR doesn't need a new one — update the existing doc/ADR with a dated note instead (see ADR-0007's amendment for the pattern).
- **Don't mock the database in tests that are supposed to verify persistence.** DB-dependent tests use the real `db_session` fixture (`tests/conftest.py`) and skip (via `pytest.skip`, not xfail) when Postgres isn't reachable — never substitute a mock for the thing actually being tested (constraint enforcement, idempotency, ordering).
- **Tests and local manual dev currently share one Postgres instance** — running `scripts/generate_synthetic_events.py --seed-db` and then `pytest` against the same database can leave Alembic's version table stale (tracked in `docs/OPEN_QUESTIONS.md`). If `alembic upgrade head` silently no-ops against a database that's missing its tables, that's why — drop `alembic_version` and re-run it, don't assume the migration is broken. In CI, this is why the seed/export/dbt steps run *before* pytest, not after.
- **The dbt project (`backend/analytics/`) is a separate tool, run separately.** It's not installed as a base dependency (`pyproject.toml`'s `analytics` extra) and not invoked by the FastAPI app. Don't add a `subprocess` call to `dbt` from application code, and don't add `dbt-core`/`dbt-duckdb`/`pandas`/`pyarrow` to the base `dependencies` list — the API doesn't need them to run.
- **A new event type needs its dbt test list updated too.** `backend/analytics/models/cleaned/_cleaned__models.yml`'s `accepted_values` test on `event_type` is a literal list that must mirror `backend/app/events/event_types.py` by hand (tracked in `docs/OPEN_QUESTIONS.md`) — add both together, not just the Python side.
- **A new dbt model needs a clear analytical purpose, not just plausibility.** `docs/ENGINEERING_ROADMAP.md`'s Milestone 3 non-goal is explicit: no dbt model should duplicate application logic (e.g. the event-ingestion projector) without a reason beyond "it could be useful."

## Before implementing a new area of the system

1. Check whether an ADR already covers the decision; if it contradicts what you're about to do, stop and raise it rather than overriding silently.
2. Check `docs/OPEN_QUESTIONS.md` — if what you're about to build depends on an open question, implement the smallest version that doesn't require resolving it, or ask.
3. Keep the metric contract framework (`docs/OPERATIONAL_DOMAIN_MODEL.md` §2.4) in mind for anything metrics-adjacent — new metrics get a contract, not just a column.

## Commands

```bash
cd backend
pip install -e ".[dev]"
pytest              # run tests (DB-dependent ones skip honestly if Postgres isn't reachable)
ruff check .        # lint
alembic upgrade head   # apply migrations (needed once per fresh database)
uvicorn app.main:app --reload   # run the API locally
python scripts/generate_synthetic_events.py --seed 42 --seed-db   # seed reference data + a sample stream

# analytics pipeline (needs the `analytics` extra: pip install -e ".[dev,analytics]")
python scripts/export_events_to_parquet.py --out ../data/processed/events.parquet
cd analytics && dbt run --profiles-dir . && dbt test --profiles-dir .

# or, from the repo root, the full stack:
docker compose up -d
```

CI (`.github/workflows/ci.yml`) runs lint, `alembic upgrade head`, seed + export + `dbt run`/`dbt test`, then `pytest` — in that order (pytest last, because its own schema teardown would otherwise wipe the seeded data the dbt steps need) — against a real Postgres service container on every push/PR to `main`. Run the same sequence locally before pushing, don't rely on CI to catch it first. After any code change, actually run the tests and report what happened; don't report a change as done on the basis that it "should work."
