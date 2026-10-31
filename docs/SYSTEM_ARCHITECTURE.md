# System Architecture

## Guiding shape: modular monolith

StationOS is one deployable backend (`backend/`) with strict internal module boundaries, not a microservices mesh (ADR applies the "avoid premature microservices" principle directly — no dedicated ADR number since it's a default, not a one-time decision; revisit only if a specific module needs independent scaling/deployment that the monolith can't accommodate). FastAPI + SQLAlchemy + Alembic + PostgreSQL + DuckDB, per `docs/DATA_ARCHITECTURE.md`.

## Six layers

### Layer 1 — Operational domain
Entities from `docs/OPERATIONAL_DOMAIN_MODEL.md` (trucks, parcels, induct, sort clusters, aisles, hampers, stowers, bags, jackpot, high-value processing, carts, routes, waves, staging, vans, dispatch, returns, planning). Lives in `backend/app/domain/` — currently empty, populated starting Milestone 2.

### Layer 2 — Data and event infrastructure
Event ingestion, validation, normalisation, storage; operational state reconstruction; analytical modelling; data-quality monitoring. Spans `backend/app/db/`, `backend/app/events/`, and `backend/app/repositories/` (all implemented, Milestones 2–3), and the `data/` tree. Detailed in `docs/DATA_ARCHITECTURE.md`.

### Layer 3 — Station intelligence and digital twin
Current station state, parcel lifecycle, resource availability, queue lengths, capacity constraints, simulation scenarios, forecasts. Lives in `backend/app/simulation/`, `backend/app/analytics/` (both implemented, Milestones 4–5), and `backend/app/predictive/` (forecasts, Milestone 8 — one model so far). Detailed in `docs/DIGITAL_TWIN_SPEC.md` and `docs/PREDICTIVE_INTELLIGENCE_SPEC.md`.

### Layer 4 — Agentic AI and reinforcement learning
Two **separate but interoperable** sub-layers:
- **Agentic AI** (`backend/app/agents/`, `backend/app/orchestration/`): reasoning, investigation, planning, tool coordination, evidence gathering, explanation, memory, recommendation generation. Detailed in `docs/AGENTIC_ARCHITECTURE.md`.
- **Reinforcement learning** (`backend/app/rl/`): formally defined sequential decision problems, policy learning, simulation-based evaluation, optimisation under constraints. Detailed in `docs/RL_ENVIRONMENT_SPEC.md`.

An LLM is never a substitute for a properly defined optimisation algorithm, and an RL policy is never given authority an agent's evidence pipeline hasn't governed — the two sub-layers communicate through typed interfaces, not a shared black box.

### Layer 5 — Decision governance
Policy engine, constraint validation, risk evaluation, human approval, role-based permissions, audit records, decision provenance. Lives in `backend/app/security/` — the governance pipeline (policy engine, risk evaluation, approval, audit record, Milestone 7) and role-based permissions on who may approve (`rbac.py`, Milestone 9) are both implemented. Detailed in `docs/SECURITY_AND_GOVERNANCE.md`.

### Layer 6 — Operational experience
Station command centre, dashboards, AI copilot, investigation workspace, simulation workspace, planning workspace, decision history, model/policy evaluation views. Lives in `frontend/` — implemented (Milestone 10, both parts): a Vite + React + TypeScript SPA with seven views covering every Cycle-1/agent/simulation/RL/decision capability that has real data behind it (Cycle 2 views don't exist — no domain model, no events — so there's nothing for a view to show). See `frontend/README.md` for the dev setup and `docs/API_REFERENCE.md` for the API layer it consumes.

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

`backend/app/core/` (settings, logging) is a cross-cutting utility layer every module may depend on; it depends on nothing else in the app. `backend/app/api/` is the HTTP boundary — it orchestrates calls into the layers above but contains no business logic itself. As of Milestone 10 Part 1, this now spans every implemented layer: `routes/health.py` (Layer 2 readiness probes), `routes/analytics.py` (Layer 3), `routes/agents.py` (Layer 4), `routes/simulation.py`/`routes/rl.py` (Layer 3/4), `routes/decisions.py` (Layer 5) — each route module stays a thin wrapper, with all real logic in the module it calls into, per `docs/API_REFERENCE.md`.

A module must not reach sideways into another vertical's internals (e.g., `agents/` must not import directly from `simulation/`'s internal state — it goes through a typed service interface in `services/` or `analytics/`).

## Current implementation state

| Module | State |
|---|---|
| `app/core` | Implemented — settings (env-driven, secrets as `SecretStr` since Milestone 9, CORS allow-list since Milestone 10), structured JSON logging, deterministic-RNG helpers (`determinism.py`, Milestone 4), the `LLMProvider` abstraction (`llm/`, Milestone 5), a shared version-string convention (`versioning.py`, Milestone 9), minimal local-first tracing (`tracing.py`, Milestone 9 — plus FastAPI 0.162's own built-in HTTP span auto-instrumentation once a real `TracerProvider` is configured, Milestone 10) |
| `app/db` | Implemented — PostgreSQL (SQLAlchemy engine/session) + DuckDB (file-backed connection) connectivity, each with a readiness probe |
| `app/api/routes/` | Implemented (Milestone 1: `health.py`; Milestone 10 Part 1: `analytics.py`, `agents.py`, `simulation.py`, `rl.py`, `decisions.py`) — `/health`/`/health/ready`, plus the full read/action API for every view that has real data behind it. See `docs/API_REFERENCE.md` |
| `app/domain` | Implemented (Milestone 2, Cycle 1 only) — Station, Truck, Aisle, Hamper, Stower, Bag, Parcel ORM models + enums |
| `app/events` | Implemented (Milestones 2–4) — the event envelope/payload schemas, the `events` ORM table, `EventStore` (append-only, idempotent), and a shared Parquet writer (`parquet_io.py`, Milestone 4) used by both the PostgreSQL export and the digital twin. Not listed in the original six-layer sketch by name; it's the concrete form of Layer 2's "event ingestion/validation/storage," sitting alongside `app/db` |
| `app/repositories` | Implemented (Milestone 2, partial) — typed lookups for trucks/parcels/aisles/stowers/bags |
| `app/services` | Implemented (Milestones 2–3, partial) — reference-data seeding, the parcel/truck event projector, the synthetic Cycle-1 event generator, Parquet export (`parquet_export.py`). Still empty for anything beyond ingestion/analytics-feed |
| `app/schemas` | Implemented (Milestone 10 Part 1) — HTTP-facing request/response models (`decisions.py`, `simulation.py`, `rl.py`, `agents.py`), populated now that there's a real API-facing consumer; internal domain Pydantic models (e.g. `app/events/schemas.py`, `app/security/policy_engine.py`) still live next to what they validate, unchanged |
| `app/orchestration` | Implemented (Milestone 5; `list_executions` added Milestone 10 for the API layer) — `AgentDefinition`/`AgentExecutor` (`runner.py`, now span-instrumented), the `agent_executions` audit table (`models.py`), its repository functions. See ADR-0005 |
| `app/agents` | Implemented (Milestone 5, one agent) — shared evidence types (`schemas.py`: `EvidenceCategory`, `Finding`), the Flow Intelligence Agent (`flow_intelligence/`). See `docs/AGENTIC_ARCHITECTURE.md` |
| `app/analytics` | Implemented (Milestone 5) — `duckdb_queries.py`, the Python-side query interface onto the Milestone 3 analytics DuckDB file this doc always said would arrive "once an API/agent consumer needs it." The Flow Intelligence Agent is that consumer. The dbt project at `backend/analytics/` remains the actual transformation logic (see `docs/DATA_ARCHITECTURE.md`); this module only reads its output, read-only |
| `app/simulation` | Implemented (Milestones 4 & 6; shipped-scenario allow-list added Milestone 10) — `config.py` (YAML scenario loading; `list_shipped_scenarios`/`resolve_shipped_scenario_path` — the path-traversal-safe lookup the API layer requires, see `docs/API_REFERENCE.md`), `model.py` (the SimPy process model, now with a `StowPriorityProvider` hook and a `setup_simulation()` entry point for incremental stepping, added for Milestone 6), `export.py` (writes simulation output to Parquet + a run manifest). Reads from `app/domain`/`app/events` (Layer 1/2), as the module dependency direction allows |
| `app/rl` | Implemented (Milestone 6, one decision problem) — `env.py` (`StowBalancingEnv`, a Gymnasium environment wrapping `app/simulation` incrementally), `baselines.py` (static + rule-based + `FixedWeightPolicy`, Milestone 7), `evaluation.py` (per-seed episode running + aggregation, Milestone 7 — extracted from `scripts/run_rl_evaluation.py` so the Milestone 6 report and Milestone 7's candidate evaluation share one implementation). See `docs/RL_ENVIRONMENT_SPEC.md` |
| `app/security` | Implemented (Milestones 7 & 9) — `models.py` (`DecisionRecord`, now also `approver_role`/`component_versions`), `repository.py` (approve/reject/record-outcome, the only place a record's status changes, now RBAC-checked and re-validating every JSONB argument against its Pydantic schema), `policy_engine.py` (rule-based eligibility/constraint checks, plus `CandidateRecord` for persisted-shape validation), `risk.py` (a minimal, explicitly-labeled stub), `rbac.py` (Milestone 9 — `Role`, a fixed role/decision-type permission table, `check_can_approve`), `decision_service.py` (the coordination logic: evaluates candidates via `app/rl`, runs the policy engine, persists a `DecisionRecord`, supports shadow-mode proposals). See `docs/SECURITY_AND_GOVERNANCE.md` and ADR-0009 |
| `app/predictive` | Implemented (Milestone 8, one model) — `jackpot_risk/` (`dataset.py`, `model.py`, `evaluation.py`, `schemas.py`, `predict.py`): a logistic-regression jackpot-accumulation-risk classifier trained on Milestone 4 twin episodes, evaluated against two baselines with temporal (seed-ordered) train/test validation. See `docs/PREDICTIVE_INTELLIGENCE_SPEC.md` |
| `alembic/` | Wired to `app.db.postgres.Base.metadata`; four migrations (`e3e6c2908dde` Cycle-1 schema, `87b9a804de1e` `agent_executions`, `57b3ef4063b0` `decision_records`, `8a19c7f88922` adds `approver_role`/`component_versions`), autogenerated, verified both upgrade and downgrade |
| `backend/analytics/` | Implemented (Milestone 3) — a self-contained dbt Core project (`dbt_project.yml` + `profiles.yml` in-project, no `~/.dbt/` dependency) with `raw`/`cleaned`/`curated`/`operational_intelligence` layered models against DuckDB, and 30 dbt tests. Verified (Milestone 4) to run unmodified against simulated Parquet output, not just real data. See `docs/DATA_ARCHITECTURE.md` |
| `backend/scripts/generate_synthetic_events.py` | Implemented (Milestone 2) — CLI to generate a seeded Cycle-1 event stream, optionally write it as JSON under `data/synthetic/`, optionally ingest it into PostgreSQL |
| `backend/scripts/export_events_to_parquet.py` | Implemented (Milestone 3) — CLI exporting the PostgreSQL `events` table to `data/processed/events.parquet` for the dbt project to read |
| `backend/scripts/run_simulation.py` | Implemented (Milestone 4) — CLI running a scenario YAML file and writing its output as Parquet + a run manifest |
| `backend/scripts/train_rl_policy.py` | Implemented (Milestone 6) — CLI training a PPO policy against `StowBalancingEnv`, saving it to `ml/models/` |
| `backend/scripts/run_rl_evaluation.py` | Implemented (Milestone 6) — CLI comparing static/rule-based/PPO policies across seeds and held-out scenarios, writing an evaluation report |
| `backend/scripts/run_decision_demo.py` | Implemented (Milestone 7) — CLI demonstrating the full decision-governance pipeline end to end: propose → policy engine → (refused) outcome-before-approval → human approval → observed-outcome simulation run, against real Postgres |
| `backend/scripts/train_jackpot_risk_model.py` | Implemented (Milestone 8) — CLI building the jackpot-risk dataset, splitting it temporally, training/evaluating all candidates on held-out episodes and held-out scenario variations, and saving the trained model |
| `simulation/scenarios/` (top-level) | Implemented (Milestone 4) — `normal_operations.yaml`, `delayed_inbound_trucks.yaml` |
| `frontend/`, `infra/`, `ml/` | Placeholder directories only |

## Deployment topology (local-first)

Docker Compose (implemented, Milestone 1) brings up the FastAPI backend container and a PostgreSQL container; a frontend dev server joins later (Milestone 10). DuckDB is embedded — no server/container of its own, just a file under `data/analytics/`.

## Observability

Structured JSON logging via `structlog` is already in place; the orchestration layer (Milestone 5) logs each agent execution's lifecycle (`agent_execution.started`/`checkpointed`/`completed`/`attempt_failed`/`degraded`) tagged with its `execution_id`, giving per-run correlation without a separate tracing system.

**Implemented (Milestone 9)**: `backend/app/core/tracing.py` — a minimal OpenTelemetry integration, deliberately local-first: a `SimpleSpanProcessor` + `ConsoleSpanExporter` only, no external collector, no mandatory cloud service (the same "no premature infrastructure" stance as ADR-0001/ADR-0010). `AgentExecutor.run`/`resume` and `app/security/decision_service.py`'s `propose_decision`/`observe_outcome` are instrumented with spans, correlating the multi-step operations each one runs (evidence gathering, interpretation attempts; candidate evaluation, policy engine, persistence). Honest framing: every component here is still one Python process — there is no real network/process hop yet to call genuinely "distributed" — so this is tracing for step-level correlation and duration within one operation, not distributed tracing in the strict sense. Revisit a real exporter/collector only once an actual hop exists (a future API consumer, a future worker process).

**Bonus found, Milestone 10**: FastAPI 0.162 ships its own built-in OpenTelemetry integration — once `configure_tracing()` sets a real `TracerProvider`, every HTTP request through `app/main.py` automatically gets a `SERVER`-kind span with standard attributes (`http.route`, `http.response.status_code`, etc.), with no extra package or code. This now gets a genuine (if still single-process) request/response hop to correlate against the explicit spans above.
