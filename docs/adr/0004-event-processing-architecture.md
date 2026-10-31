# ADR-0004: Event-processing architecture

**Status**: Accepted

## Context

StationOS needs to represent operational activity as structured, typed events (truck arrival, induct scan, sort divert, stow, dispatch, etc.), with explicit handling of duplicate, delayed, missing, and out-of-order events — this is foundational to everything built on top (analytics, digital twin calibration input shape, agent evidence).

## Options considered

1. **Message broker (Kafka or similar) from the start.** Rejected for v1: StationOS has no actual streaming/fan-out requirement yet — no second independent consumer, no throughput that a database can't handle. Adopting Kafka now would be infrastructure introduced for architectural appearance, which the project's own principles explicitly reject.
2. **No formal event model — just mutate current state directly in Postgres.** Rejected: loses the event history needed for analytics, replay, dwell-time calculation, and digital-twin/real-data comparability; makes duplicate/out-of-order handling an afterthought instead of a designed property.
3. **A reliable, modular event-processing implementation on top of PostgreSQL** (typed events with `event_id`, `idempotency_key`, `correlation_id`, `schema_version`, `occurred_at`/`recorded_at`, provenance; stored as an append-only table; projected into current-state tables). Chosen.

## Decision

Events are typed, versioned, and carry the fields listed above (full spec in `docs/DATA_ARCHITECTURE.md`). They are persisted in PostgreSQL as the event log of record, with explicit, testable handling of duplicates (idempotency key), delay (occurred_at vs. recorded_at skew), missing events (sequence-gap detection), and out-of-order arrival (sort by occurred_at). No message broker is introduced at this stage.

## Rationale

This satisfies every stated requirement (typed events, idempotency, provenance, ordering) without adopting distributed-systems infrastructure the project doesn't yet have a workload to justify. It is also easier to reason about and test locally, consistent with the local-first principle (ADR-0001).

## Consequences

- Event throughput and fan-out are bounded by what a single PostgreSQL instance can do — acceptable at this project's current and foreseeable near-term scale.
- Adding a real streaming layer later means adding a consumer of the existing event log, not redesigning the event model itself (the typed-event contract is broker-agnostic by construction).

## Risks

- If a genuine multi-consumer, high-throughput streaming need emerges, retrofitting a broker is nontrivial — mitigated by keeping the event *schema* broker-agnostic now, even though the *transport* is just Postgres.

## Revisit conditions

Revisit when an actual requirement exists for independent, real-time multi-consumer event fan-out, or when induct-time processing latency requirements can't be met by batch/polling consumption of the Postgres event log.
