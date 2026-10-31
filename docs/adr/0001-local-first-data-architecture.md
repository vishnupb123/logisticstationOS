# ADR-0001: Local-first data architecture

**Status**: Accepted

## Context

StationOS must run on a developer's laptop using open-source technologies, without requiring a paid cloud data warehouse, managed database, or vendor-specific account for its foundational workflows. It also needs a credible path to serious analytical and operational-intelligence work, not just a toy data layer.

## Options considered

1. **Cloud-first** (e.g., Snowflake + managed Postgres from day one). Rejected: creates a mandatory paid dependency and an account-provisioning step before anyone can run the project.
2. **Single local database for everything** (e.g., Postgres only, or DuckDB only). Rejected: Postgres is weak for ad hoc analytical/columnar workloads at scale; DuckDB is not designed as a concurrent transactional store. Forcing one workload onto the wrong tool trades a small simplicity gain for a correctness/performance mismatch.
3. **Local-first, multi-tool, with explicit responsibility boundaries** (PostgreSQL + DuckDB + Parquet + dbt Core). Chosen.

## Decision

StationOS's foundational data stack is PostgreSQL (operational/transactional), DuckDB (local analytical SQL), Parquet (portable columnar storage), and dbt Core (transformation/modelling), all runnable locally via Docker Compose with no paid service required. Cloud warehouse integrations (Snowflake, Databricks, BigQuery) may be added later as optional adapters (see ADR-0010), never as a requirement.

## Rationale

Each tool is chosen for what it's actually good at, not for enterprise-architecture appearance. This keeps the barrier to entry at "clone and `docker compose up`," which matters for a project intended to become public and for keeping engineering honest about what's actually needed versus what looks impressive in a diagram.

## Consequences

- Local development has no cloud cost and no account-provisioning step.
- Any future cloud integration is additive, not a rewrite.
- The team must maintain discipline about which store owns which workload (see ADR-0002) rather than letting one creep into the other's job.

## Risks

- Local-only analytical capacity (DuckDB on a laptop) won't scale to production data volumes StationOS doesn't have yet — acceptable now, revisit when it's a real constraint.

## Revisit conditions

Revisit if StationOS needs to run in a shared/production environment where "a developer's laptop" is no longer the deployment target, or if DuckDB's single-node analytical capacity becomes an actual bottleneck against real data volume.
