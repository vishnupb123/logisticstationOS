# Data Architecture

## Principle

Local-first, open-source-first (ADR-0001). PostgreSQL, DuckDB, Parquet, and dbt Core serve **different purposes** and are not interchangeable — forcing every workload into one of them is a design smell, not a simplification.

## Responsibilities

| Store | Owns | Rationale |
|---|---|---|
| **PostgreSQL** | Operational/transactional state: current entity state (parcels, carts, routes, waves...), event log of record, anything requiring ACID writes or concurrent read/write access | It's the system of record. Anything the application *writes* during normal operation goes here first. See ADR-0002. |
| **DuckDB** | Local analytical SQL — ad hoc queries, metric computation, dashboard-backing aggregates | Embedded, zero-ops, fast columnar analytics over data exported from Postgres or read directly from Parquet. Not a system of record — rebuildable from Parquet/Postgres at any time. See ADR-0002. |
| **Parquet** | Portable columnar storage for historical events and analytical snapshots | Durable, engine-independent format; what DuckDB reads directly and what a future warehouse adapter would ingest. See ADR-0003. |
| **dbt Core** | Transformation/modelling logic that turns raw events into analytical tables | Reproducible, version-controlled SQL transformations, run against DuckDB locally (and, later, against whichever analytical warehouse is configured). |

`backend/app/db/postgres.py` and `backend/app/db/duckdb.py` implement the connection layer for the first two; `data/raw/`, `data/processed/`, `data/synthetic/`, `data/analytics/` hold the Parquet/DuckDB-file side (gitignored contents — regenerate via the scripts below, don't expect them to be present after a fresh clone).

## Data flow (implemented, Milestone 3)

```
Domain events (app/domain, written via app/repositories)
        │
        ▼
PostgreSQL events table (event log of record)
        │  backend/scripts/export_events_to_parquet.py (batch export, manual/on-demand — no scheduler yet)
        ▼
data/processed/events.parquet  (one file, overwritten on each export — not yet partitioned or incremental)
        │
        ▼
dbt Core project (backend/analytics/): raw → cleaned → curated → operational_intelligence
        ▼
DuckDB (data/analytics/stationos.duckdb)  — the same file app/db/duckdb.py's connection manager uses
        │
        ▼
Queried directly (via `duckdb`/Python) today; an app/analytics service + API route is deferred
until a real consumer needs one (an agent in Milestone 5+, the frontend in Milestone 10) — see
docs/ENGINEERING_ROADMAP.md.
```

`data/raw/` holds unprocessed inputs (e.g., synthetic event generator output before validation); `data/synthetic/` holds the generated synthetic datasets themselves (scenario fixtures for the digital twin and for seeding Postgres in dev). Neither is used by the Milestone 3 pipeline above, which exports directly from PostgreSQL to `data/processed/`.

### dbt project layering (`backend/analytics/`)

| Layer | Models | Purpose |
|---|---|---|
| `raw` | `raw_events` | Literal `read_parquet()` of the export — no transformation |
| `cleaned` | `cleaned_events` | Typed envelope columns; `payload` cast to JSON for downstream parsing |
| `curated` | `curated_parcel_events`, `curated_parcel_lifecycle` | Payload fields flattened into typed columns; one row per parcel with key lifecycle timestamps — the analytical-layer counterpart to `app/services/event_ingestion.py`'s projector, kept separately testable rather than shared code, since the two have different jobs (maintaining Postgres's current-state rows per write vs. restating the same facts as a queryable batch view) |
| `operational_intelligence` | `metric_induct_throughput`, `metric_jackpot_volume`, `metric_parcel_dwell_time`, `metric_stow_throughput`, `metric_wips` | The five `proposed`-status metrics from `docs/OPERATIONAL_DOMAIN_MODEL.md` §4.1 that don't require organization-specific validation |

Run it: `cd backend/analytics && dbt run --profiles-dir . && dbt test --profiles-dir .` (after exporting Parquet — see `HANDOFF.md` for the full command sequence). `event_type`'s accepted-values test (`models/cleaned/_cleaned__models.yml`) must be kept in sync by hand with `backend/app/events/event_types.py` — there's no automated check that they match; tracked in `docs/OPEN_QUESTIONS.md`.

## Event schema conventions

Every domain event carries:

| Field | Purpose |
|---|---|
| `event_id` | Unique identifier for this event instance |
| `idempotency_key` | Lets a consumer safely discard a duplicate delivery of the same logical event |
| `correlation_id` | Ties together events belonging to the same parcel/process/request |
| `schema_version` | Explicit version so consumers can handle schema evolution deliberately |
| `occurred_at` | When the event happened in the domain (not when it was recorded) |
| `recorded_at` | When the system persisted it — distinguishing the two makes delayed/out-of-order events detectable |
| `provenance` | Where the event came from (which scanner/service/synthetic generator) |
| `source_kind` | What *kind* of fact this is — `physical_observation`, `system_recorded`, `inferred`, or `simulated` — never conflated with each other downstream |

Explicit handling is required (not optional) for: duplicate events (via `idempotency_key`), delayed events (via `occurred_at` vs `recorded_at` skew), missing events (gaps detectable via expected-sequence checks per entity), and out-of-order events (sort by `occurred_at`, not arrival order).

**Implemented (Milestone 2)**: a single append-only `events` table (`backend/app/events/models.py`), not one table per event type — ADR-0004's "append-only event table" resolved concretely this way (`docs/OPEN_QUESTIONS.md`). `EventStore.append()` (`backend/app/events/store.py`) enforces the idempotency guarantee at the database level via a unique constraint on `idempotency_key` with `INSERT ... ON CONFLICT DO NOTHING`, not just application discipline. Current entity state (a parcel's or truck's row under `app/domain/`) is a **projection**, rebuilt by replaying that entity's full event history in `occurred_at` order every time a new event arrives for it (`backend/app/services/event_ingestion.py`) — this is what makes out-of-order and duplicate delivery safe: the projection is a pure function of the event log's content, never of arrival order. An event whose predecessor is missing or wrong (e.g. a stow event with no prior sort) is still persisted and still projected from — never silently dropped — but the projection is flagged `lifecycle_consistent = False` with a human-readable note, which is the concrete form of "never assume virtual state matches physical state."

## Optional analytical warehouse abstraction

Snowflake, Databricks, BigQuery, or another compatible analytical platform may be introduced **later**, strictly as an optional adapter, never a required dependency for foundational workflows (ADR-0010). The shape: an abstract analytical-warehouse interface (query, load, schema-sync) that DuckDB satisfies locally today; a Snowflake/Databricks/BigQuery adapter would implement the same interface. No adapter beyond DuckDB exists yet — building one now, before there's a concrete need, would be exactly the kind of premature integration this project is trying to avoid.

If Snowflake tooling exists on a developer's machine, StationOS code must never assume valid account access or read credentials beyond checking *whether* configuration is present (by environment variable name, never by value) — see `docs/SECURITY_AND_GOVERNANCE.md`.

## Data quality

**Implemented (Milestone 3)** as dbt tests (`backend/analytics/`), rather than only as the Python-layer projector's `lifecycle_consistent` flag — an analytics consumer querying DuckDB directly has no visibility into that application-layer flag, so the same invariants are reinforced here:

| Check | How |
|---|---|
| Completeness (expected event sequence per parcel) | `tests/assert_no_missing_induct_event.sql` — a non-`parcel.inducted` event whose entity never had one is a failure |
| Timestamp validity | `tests/assert_occurred_at_not_after_recorded_at.sql` — an event can't be recorded before it happened |
| Valid event types | `accepted_values` test on `cleaned_events.event_type`, against the literal list in `backend/app/events/event_types.py` (manually kept in sync — see `docs/OPEN_QUESTIONS.md`) |
| Null/uniqueness | `not_null`/`unique` generic tests across `raw_events`, `cleaned_events`, and the curated/metric layers |
| Metric-contract requirements | `assert_no_negative_dwell_time.sql`, `assert_jackpot_volume_non_negative.sql` — a metric's own internal invariants, not just its inputs' |

Not yet implemented: schema-conformance checks against `schema_version` (only one version of each event type exists so far — nothing to check conformance *against* yet) and freshness checks (`recorded_at - occurred_at` skew) — there's no live/streaming consumer yet for whom freshness would matter; revisit when one exists.
