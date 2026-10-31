# System Architecture

## Guiding shape: modular monolith

StationOS is one deployable backend (`backend/`) with strict internal module boundaries, not a microservices mesh (ADR applies the "avoid premature microservices" principle directly — no dedicated ADR number since it's a default, not a one-time decision; revisit only if a specific module needs independent scaling/deployment that the monolith can't accommodate). FastAPI + SQLAlchemy + Alembic + PostgreSQL + DuckDB, per `docs/DATA_ARCHITECTURE.md`.

## Six layers

### Layer 1 — Operational domain
Entities from `docs/OPERATIONAL_DOMAIN_MODEL.md` (trucks, parcels, induct, sort clusters, aisles, hampers, stowers, bags, jackpot, high-value processing, carts, routes, waves, staging, vans, dispatch, returns, planning). Lives in `backend/app/domain/` — currently empty, populated starting Milestone 2.

### Layer 2 — Data and event infrastructure
Event ingestion, validation, normalisation, storage; operational state reconstruction; analytical modelling; data-quality monitoring. Spans `backend/app/db/`, `backend/app/events/`, and `backend/app/repositories/` (all implemented, Milestones 2–3), and the `data/` tree. Detailed in `docs/DATA_ARCHITECTURE.md`.

### Layer 3 — Station intelligence and digital twin
Current station state, parcel lifecycle, resource availability, queue lengths, capacity constraints, simulation scenarios, forecasts. Lives in `backend/app/simulation/` and `backend/app/analytics/` (both implemented, Milestones 4–5). Detailed in `docs/DIGITAL_TWIN_SPEC.md`.

### Layer 4 — Agentic AI and reinforcement learning
Two **separate but interoperable** sub-layers:
- **Agentic AI** (`backend/app/agents/`, `backend/app/orchestration/`): reasoning, investigation, planning, tool coordination, evidence gathering, explanation, memory, recommendation generation. Detailed in `docs/AGENTIC_ARCHITECTURE.md`.
- **Reinforcement learning** (`backend/app/rl/`): formally defined sequential decision problems, policy learning, simulation-based evaluation, optimisation under constraints. Detailed in `docs/RL_ENVIRONMENT_SPEC.md`.

An LLM is never a substitute for a properly defined optimisation algorithm, and an RL policy is never given authority an agent's evidence pipeline hasn't governed — the two sub-layers communicate through typed interfaces, not a shared black box.

### Layer 5 — Decision governance
Policy engine, constraint validation, risk evaluation, human approval, role-based permissions, audit records, decision provenance. Lives in `backend/app/security/` (empty). Detailed in `docs/SECURITY_AND_GOVERNANCE.md`.

### Layer 6 — Operational experience
Station command centre, dashboards, AI copilot, investigation workspace, simulation workspace, planning workspace, decision history, model/policy evaluation views. Lives in `frontend/` (not started).

## Module dependency direction

Layers depend **downward only**:

```
Layer 6 (frontend)
   ↓ HTTP (backend/app/api)
Layer 5 (security/governance)  ←  gates actions from Layer 4
   ↓
Layer 4 (agents/orchestration, rl)  ←  reads from Layer 3
   ↓
Layer 3 (simulation, analytics)  ←  reads from Layer 2
   ↓
Layer 2 (db, repositories)  ←  persists/reads Layer 1
   ↓
Layer 1 (domain)
```

`backend/app/core/` (settings, logging) is a cross-cutting utility layer every module may depend on; it depends on nothing else in the app. `backend/app/api/` is the HTTP boundary — it orchestrates calls into the layers above but contains no business logic itself (currently just `routes/health.py`, which probes Layer 2 directly since there's no Layer 3+ yet).

A module must not reach sideways into another vertical's internals (e.g., `agents/` must not import directly from `simulation/`'s internal state — it goes through a typed service interface in `services/` or `analytics/`).

## Current implementation state

| Module | State |
|---|---|
| `app/core` | Implemented — settings (env-driven), structured JSON logging, deterministic-RNG helpers (`determinism.py`, Milestone 4), the `LLMProvider` abstraction (`llm/`, Milestone 5) |
| `app/db` | Implemented — PostgreSQL (SQLAlchemy engine/session) + DuckDB (file-backed connection) connectivity, each with a readiness probe |
| `app/api/routes/health.py` | Implemented — `/health` (liveness), `/health/ready` (dependency readiness) |
| `app/domain` | Implemented (Milestone 2, Cycle 1 only) — Station, Truck, Aisle, Hamper, Stower, Bag, Parcel ORM models + enums |
| `app/events` | Implemented (Milestones 2–4) — the event envelope/payload schemas, the `events` ORM table, `EventStore` (append-only, idempotent), and a shared Parquet writer (`parquet_io.py`, Milestone 4) used by both the PostgreSQL export and the digital twin. Not listed in the original six-layer sketch by name; it's the concrete form of Layer 2's "event ingestion/validation/storage," sitting alongside `app/db` |
| `app/repositories` | Implemented (Milestone 2, partial) — typed lookups for trucks/parcels/aisles/stowers/bags |
| `app/services` | Implemented (Milestones 2–3, partial) — reference-data seeding, the parcel/truck event projector, the synthetic Cycle-1 event generator, Parquet export (`parquet_export.py`). Still empty for anything beyond ingestion/analytics-feed |
| `app/schemas` | Still empty — Pydantic schemas so far live next to what they validate (`app/events/schemas.py`) rather than in a separate top-level module; revisit if that stops making sense once API-facing schemas are needed |
| `app/orchestration` | Implemented (Milestone 5) — `AgentDefinition`/`AgentExecutor` (`runner.py`), the `agent_executions` audit table (`models.py`), its repository functions. See ADR-0005 |
| `app/agents` | Implemented (Milestone 5, one agent) — shared evidence types (`schemas.py`: `EvidenceCategory`, `Finding`), the Flow Intelligence Agent (`flow_intelligence/`). See `docs/AGENTIC_ARCHITECTURE.md` |
| `app/analytics` | Implemented (Milestone 5) — `duckdb_queries.py`, the Python-side query interface onto the Milestone 3 analytics DuckDB file this doc always said would arrive "once an API/agent consumer needs it." The Flow Intelligence Agent is that consumer. The dbt project at `backend/analytics/` remains the actual transformation logic (see `docs/DATA_ARCHITECTURE.md`); this module only reads its output, read-only |
| `app/simulation` | Implemented (Milestones 4 & 6) — `config.py` (YAML scenario loading), `model.py` (the SimPy process model, now with a `StowPriorityProvider` hook and a `setup_simulation()` entry point for incremental stepping, added for Milestone 6), `export.py` (writes simulation output to Parquet + a run manifest). Reads from `app/domain`/`app/events` (Layer 1/2), as the module dependency direction allows |
| `app/rl` | Implemented (Milestone 6, one decision problem) — `env.py` (`StowBalancingEnv`, a Gymnasium environment wrapping `app/simulation` incrementally), `baselines.py` (static + rule-based policies). See `docs/RL_ENVIRONMENT_SPEC.md` |
| `app/security` | Scaffolded (empty), Milestone 7 |
| `alembic/` | Wired to `app.db.postgres.Base.metadata`; two migrations (`e3e6c2908dde` Cycle-1 schema, `87b9a804de1e` `agent_executions`), autogenerated, verified both upgrade and downgrade |
| `backend/analytics/` | Implemented (Milestone 3) — a self-contained dbt Core project (`dbt_project.yml` + `profiles.yml` in-project, no `~/.dbt/` dependency) with `raw`/`cleaned`/`curated`/`operational_intelligence` layered models against DuckDB, and 30 dbt tests. Verified (Milestone 4) to run unmodified against simulated Parquet output, not just real data. See `docs/DATA_ARCHITECTURE.md` |
| `backend/scripts/generate_synthetic_events.py` | Implemented (Milestone 2) — CLI to generate a seeded Cycle-1 event stream, optionally write it as JSON under `data/synthetic/`, optionally ingest it into PostgreSQL |
| `backend/scripts/export_events_to_parquet.py` | Implemented (Milestone 3) — CLI exporting the PostgreSQL `events` table to `data/processed/events.parquet` for the dbt project to read |
| `backend/scripts/run_simulation.py` | Implemented (Milestone 4) — CLI running a scenario YAML file and writing its output as Parquet + a run manifest |
| `backend/scripts/train_rl_policy.py` | Implemented (Milestone 6) — CLI training a PPO policy against `StowBalancingEnv`, saving it to `ml/models/` |
| `backend/scripts/run_rl_evaluation.py` | Implemented (Milestone 6) — CLI comparing static/rule-based/PPO policies across seeds and held-out scenarios, writing an evaluation report |
| `simulation/scenarios/` (top-level) | Implemented (Milestone 4) — `normal_operations.yaml`, `delayed_inbound_trucks.yaml` |
| `frontend/`, `infra/`, `ml/` | Placeholder directories only |

## Deployment topology (local-first)

Docker Compose (implemented, Milestone 1) brings up the FastAPI backend container and a PostgreSQL container; a frontend dev server joins later (Milestone 10). DuckDB is embedded — no server/container of its own, just a file under `data/analytics/`.

## Observability

Structured JSON logging via `structlog` is already in place; the orchestration layer (Milestone 5) logs each agent execution's lifecycle (`agent_execution.started`/`checkpointed`/`completed`/`attempt_failed`/`degraded`) tagged with its `execution_id`, giving per-run correlation without a separate tracing system. OpenTelemetry remains deferred — one agent, one process, no distributed hop yet to trace — revisit once multi-agent orchestration (Milestone 7+) makes a single request span multiple agents/processes worth correlating across.
