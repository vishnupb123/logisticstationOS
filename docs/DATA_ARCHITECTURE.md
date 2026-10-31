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

`backend/app/db/postgres.py` and `backend/app/db/duckdb.py` already implement the connection layer for the first two; `data/raw/`, `data/processed/`, `data/synthetic/`, `data/analytics/` are the placeholder directories for the Parquet/DuckDB-file side (currently empty, gitignored contents).

## Data flow (target shape)

```
Domain events (app/domain, written via app/repositories)
        │
        ▼
PostgreSQL (operational event log + current state)
        │  periodic export / CDC-style batch (Milestone 3)
        ▼
Parquet files under data/processed/  (immutable, append-oriented)
        │
        ▼
dbt Core models  ──────────────▶  DuckDB (data/analytics/stationos.duckdb)
        │
        ▼
Analytical services (app/analytics) ──▶ API ──▶ frontend dashboards / agent evidence queries
```

`data/raw/` holds unprocessed inputs (e.g., synthetic event generator output before validation); `data/synthetic/` holds the generated synthetic datasets themselves (scenario fixtures for the digital twin and for seeding Postgres in dev).

## Event schema conventions

Every domain event (Milestone 2+) carries:

| Field | Purpose |
|---|---|
| `event_id` | Unique identifier for this event instance |
| `idempotency_key` | Lets a consumer safely discard a duplicate delivery of the same logical event |
| `correlation_id` | Ties together events belonging to the same parcel/process/request |
| `schema_version` | Explicit version so consumers can handle schema evolution deliberately |
| `occurred_at` | When the event happened in the domain (not when it was recorded) |
| `recorded_at` | When the system persisted it — distinguishing the two makes delayed/out-of-order events detectable |
| `provenance` | Where the event came from (which scanner/service/synthetic generator) |

Explicit handling is required (not optional) for: duplicate events (via `idempotency_key`), delayed events (via `occurred_at` vs `recorded_at` skew), missing events (gaps detectable via expected-sequence checks per entity), and out-of-order events (sort by `occurred_at`, not arrival order). The concrete mechanism (outbox table, append-only event table, etc.) is deferred to Milestone 2 — see ADR-0004 for why this starts as a reliable modular implementation rather than a message broker.

## Optional analytical warehouse abstraction

Snowflake, Databricks, BigQuery, or another compatible analytical platform may be introduced **later**, strictly as an optional adapter, never a required dependency for foundational workflows (ADR-0010). The shape: an abstract analytical-warehouse interface (query, load, schema-sync) that DuckDB satisfies locally today; a Snowflake/Databricks/BigQuery adapter would implement the same interface. No adapter beyond DuckDB exists yet — building one now, before there's a concrete need, would be exactly the kind of premature integration this project is trying to avoid.

If Snowflake tooling exists on a developer's machine, StationOS code must never assume valid account access or read credentials beyond checking *whether* configuration is present (by environment variable name, never by value) — see `docs/SECURITY_AND_GOVERNANCE.md`.

## Data quality

Deferred to Milestone 3 in concrete form, but the shape is: completeness checks (expected event sequence per parcel/entity), freshness checks (recorded_at - occurred_at skew), and schema-conformance checks (event validates against its declared `schema_version`). These feed the "data-quality requirements" field of the metric contract (`docs/OPERATIONAL_DOMAIN_MODEL.md` §4) — a metric should not be marked `validated` if its required source events don't yet pass these checks.
