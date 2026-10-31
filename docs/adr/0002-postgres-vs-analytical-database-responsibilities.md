# ADR-0002: PostgreSQL vs. analytical database responsibilities

**Status**: Accepted

## Context

With both PostgreSQL and DuckDB in the stack (ADR-0001), there must be a clear rule for which workloads go where — otherwise every future feature re-litigates "which database do I use."

## Options considered

1. **Postgres for everything, DuckDB unused until "we need analytics."** Rejected: defers the real decision rather than making it, and risks organically growing analytical queries against the transactional store.
2. **DuckDB for everything, Postgres only for locking/concurrency edge cases.** Rejected: DuckDB is not built for concurrent transactional writes; this inverts the tools' actual strengths.
3. **Strict responsibility split: Postgres owns operational/transactional state; DuckDB owns local analytical querying, fed from Postgres/Parquet, and is treated as rebuildable, never as a system of record.** Chosen.

## Decision

PostgreSQL is the system of record for all operational/transactional state (current entity state, the event log of record, anything requiring ACID guarantees or concurrent read/write access). DuckDB is a local analytical query engine over data derived from Postgres (via Parquet export) — it is never written to as a primary store and can be deleted and rebuilt at any time without data loss.

## Rationale

This mirrors standard OLTP/OLAP separation, adapted to a local-first, single-node setting. It keeps the transactional store free of long-running analytical queries and keeps the analytical store free of the correctness obligations (migrations, foreign keys, concurrent writers) that come with being a system of record.

## Consequences

- Analytical services (`backend/app/analytics/`) always query DuckDB, never Postgres directly for aggregate/dashboard-style queries.
- A data pipeline step (Postgres → Parquet → DuckDB via dbt) is required infrastructure, not optional polish — see `docs/DATA_ARCHITECTURE.md`.
- Losing the DuckDB file is an inconvenience (rebuild from Parquet), not data loss.

## Risks

- Pipeline staleness: DuckDB's view of the world lags Postgres by however often the export/transform step runs. Acceptable for decision-support use cases; would need revisiting for anything requiring real-time analytical freshness.

## Revisit conditions

Revisit if a use case needs sub-second-fresh analytical queries against live transactional data (might argue for a different approach, e.g., read replicas or a different OLAP engine) — no such requirement exists yet.
