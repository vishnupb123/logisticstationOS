# ADR-0010: Optional cloud warehouse strategy

**Status**: Accepted

## Context

Snowflake, Databricks, BigQuery, and similar platforms are common enterprise analytical warehouses. StationOS's local-first principle (ADR-0001) means none can be a required dependency, but a credible enterprise-oriented platform should have a believable path to supporting them when an organization actually wants to.

## Options considered

1. **Build a Snowflake (or other) adapter now, "to be enterprise-ready."** Rejected: there is no current workload requiring it, and the project's own principles explicitly reject adopting technology for architectural appearance rather than justified need. It would also be built against guessed requirements rather than a real integration need.
2. **Never support any cloud warehouse; DuckDB is the permanent analytical engine.** Rejected: forecloses a reasonable, likely future need for organizations with existing warehouse investments, without a compelling reason to do so.
3. **Define a future-compatible analytical-warehouse abstraction now; implement zero adapters beyond DuckDB until a real one is needed.** Chosen.

## Decision

The analytical layer (`docs/DATA_ARCHITECTURE.md`) is accessed through an interface DuckDB satisfies today. Snowflake/Databricks/BigQuery/other adapters may be added later by implementing the same interface, but none are built now. Snowflake Cortex or any other vendor-specific AI/analytical feature is never assumed available; if Snowflake tooling exists locally, it may be inspected for configuration presence (by environment variable name only) but never assumed to have valid, usable account access.

## Rationale

This gets the architectural flexibility (the interface exists, a future adapter is additive) without the cost and risk of building unused, unvalidated integration code against platforms this project doesn't currently use or have access to test against meaningfully.

## Consequences

- No Snowflake/Databricks/BigQuery dependency appears in `pyproject.toml` or anywhere else until a real adapter is actually being built.
- The analytical interface's shape is derived from DuckDB's actual usage (`docs/DATA_ARCHITECTURE.md`), not pre-designed against speculative requirements from warehouses not yet integrated.
- Any future adapter work is scoped as its own milestone/ADR when there's a concrete reason, not folded silently into unrelated work.

## Risks

- Designing the interface against only one real implementation (DuckDB) risks it not fitting a future adapter cleanly — accepted, and expected to be revised when the first real adapter is built, same reasoning as ADR-0008's provider interface.

## Revisit conditions

Revisit (i.e., actually build an adapter) only when a specific, real need for a cloud analytical warehouse arises — not speculatively.
