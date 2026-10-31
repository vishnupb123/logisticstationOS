# ADR-0003: DuckDB and Parquet integration

**Status**: Accepted

## Context

Given PostgreSQL owns transactional state and DuckDB owns local analytics (ADR-0002), there needs to be a durable, portable intermediate format between them — both so historical data survives a DuckDB file being deleted/rebuilt, and so a future cloud-warehouse adapter (ADR-0010) has something standard to ingest.

## Options considered

1. **DuckDB reads Postgres directly** (via its Postgres scanner extension) with no intermediate storage. Rejected as the primary path: couples analytical queries to transactional-store availability and performance, and leaves no durable historical artifact independent of either database.
2. **Custom binary/JSON export format.** Rejected: reinvents what Parquet already does well (columnar, compressed, broadly supported, directly queryable by DuckDB with no load step).
3. **Parquet as the durable intermediate; DuckDB reads Parquet directly and/or via dbt-modelled tables.** Chosen.

## Decision**

Operational events/snapshots are periodically exported from PostgreSQL to Parquet files under `data/processed/` (and raw synthetic/generated input under `data/raw/` and `data/synthetic/`). DuckDB queries Parquet directly for simple cases and via dbt Core models for anything requiring transformation/modelling logic. Parquet is the artifact a future warehouse adapter (Snowflake/Databricks/BigQuery) would ingest, so the local and cloud-optional paths share one durable format.

## Rationale

Parquet is engine-independent, columnar, and already the natural "DuckDB reads this instantly" format — this gets durability and portability without inventing new infrastructure.

## Consequences

- `data/processed/` and `data/synthetic/` are gitignored (data, not code) but their directory structure and `.gitkeep` placeholders are committed so the layout is discoverable.
- dbt Core models define the transformation from raw/processed Parquet into analytical tables — reproducible and version-controlled, per `docs/DATA_ARCHITECTURE.md`.
- Rebuilding the entire DuckDB analytical layer from Parquet is always possible and is the expected recovery path, not an edge case.

## Risks

- Export cadence (how often Postgres → Parquet runs) directly determines analytical freshness; this is an explicit trade-off to configure, not something to leave implicit.

## Revisit conditions

Revisit the export mechanism (batch export vs. CDC-style streaming) if freshness requirements tighten beyond what periodic batch export can satisfy — not a concern yet.
