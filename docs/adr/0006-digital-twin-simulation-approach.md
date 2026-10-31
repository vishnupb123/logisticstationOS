# ADR-0006: Digital-twin simulation approach

**Status**: Accepted; amended 2026-10-31 — simulated-event output path decided (see §"Amendment" below)

## Context

StationOS needs a digital twin of the station's process (induct, sortation, stow, Pick & Stage, dispatch) to support scenario evaluation and, later, to serve as the RL training/evaluation environment.

## Options considered

1. **Continuous-time / system-dynamics modelling** (e.g., differential equations over aggregate flow rates). Rejected: the domain is fundamentally made of discrete entities (parcels, trucks, carts) and discrete resource-contention events (hamper full, jackpot divert) that continuous aggregate models obscure rather than represent.
2. **Agent-based modelling with full behavioral agents for every associate/stower.** Rejected for v1: far more modelling and calibration effort than the current, well-defined decision problems need; the roadmap's scenario catalog doesn't require individually differentiated worker behavior.
3. **Discrete-event simulation (SimPy)**, modelling resources (scanners, hampers, stowers, cage capacity), entities (parcels, trucks, carts), and processes (lifecycle flows) directly. Chosen.

## Decision

The digital twin is a SimPy-based discrete-event model (`backend/app/simulation/`), with every capacity/timing/resource count driven by an external scenario configuration rather than hardcoded, per `docs/DIGITAL_TWIN_SPEC.md`.

## Rationale

Discrete-event simulation is the natural fit for queueing/capacity-constrained processes with identifiable entities and resources, which is exactly the structure in `docs/OPERATIONAL_DOMAIN_MODEL.md`. SimPy is a mature, well-understood Python library requiring no new infrastructure, consistent with the local-first principle (ADR-0001).

## Consequences

- Scenario definitions (`docs/DIGITAL_TWIN_SPEC.md` §"Scenario catalog") are data, not code — adding a scenario shouldn't require a code change to the simulation engine itself.
- Simulation output must be structured to match the real analytical data shape (`docs/DATA_ARCHITECTURE.md`), so simulated and real data are comparable through the same pipeline.
- Reproducibility (seeded runs, versioned config) is a hard requirement from the start, since the RL layer depends on it (ADR tie-in: `docs/RL_ENVIRONMENT_SPEC.md`).

## Risks

- Calibration without real operational data to validate against (by design — synthetic-data-only project) means "calibrated" can only mean internally consistent (e.g., conservation of parcels, sane queueing behavior), not validated against ground truth. This limitation must be stated explicitly wherever twin output is used, not glossed over.

## Revisit conditions

Revisit if a later use case needs individually differentiated worker behavior modelling (agent-based) or if performance at larger scale requires a different simulation engine — neither is a current need.

## Amendment (2026-10-31): simulated-event output path

This ADR's Decision always required simulation output to be "structured to match the real analytical data shape" (§Consequences), but left open *how* that comparability is achieved. Milestone 4 resolved it:

**Decision**: the twin builds the exact same `EventEnvelope` objects the real ingestion pipeline uses (`app/events/schemas.py`), tagged `source_kind = EventSourceKind.SIMULATED` on every single event (not the Milestone 2 generator's per-event-type `physical_observation`/`system_recorded` mix — nothing in a simulation is a real observation). These are written **directly to Parquet** (`app/simulation/export.py`, reusing the same writer as the PostgreSQL export, `app/events/parquet_io.py`) — **never through PostgreSQL or `EventStore`**.

**Options considered at this fork**: (a) ingest simulated events into PostgreSQL via `EventStore`/`ingest_event`, reusing the exact same projector path as real data; (b) write simulated events straight to Parquet, bypassing PostgreSQL entirely. Chose (b).

**Rationale**: PostgreSQL is "operational/transactional state... anything requiring ACID writes" (ADR-0002) — a simulation run is neither; it's an inherently batch, ephemeral artifact of one "what if" scenario, not operational history. Routing it through `EventStore`'s idempotency machinery (built for handling real-world duplicate/delayed delivery) would exercise infrastructure built for a problem simulated data doesn't have. Comparability is achieved instead at the schema and dbt-model level: `backend/analytics/`'s `raw_events` model reads whichever Parquet file `events_parquet_path` points to, real or simulated, and every layer above it is identical either way — verified directly (not just asserted) by running the unmodified dbt project against a simulated-data Parquet file and getting the same 9 models built and 30 tests passing as against real synthetic data.

**Consequence**: PostgreSQL never contains simulated rows, so no query against it needs to filter by `source_kind` to avoid mixing simulated and real data — that risk is structurally impossible, not just avoided by discipline.
