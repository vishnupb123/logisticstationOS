# API Reference

## Status: Milestone 10, Part 1 of 2 — the API layer (2026-10-31)

`docs/ENGINEERING_ROADMAP.md` Milestone 10 is "Layer 6, a usable React/TypeScript command centre." Before any frontend scoping conversation reached a decision, the project owner explicitly chose to sequence this milestone in two parts: **build the complete backend API layer first, then the frontend that consumes it, in a separate session.** This document covers Part 1. The React frontend (Part 2) has not been started — see `HANDOFF.md`.

Until Part 1, `backend/app/api/routes/` had exactly one file (`health.py`, `/health` and `/health/ready`). This document covers everything added for Part 1: five new routers, a new `backend/app/schemas/` package for HTTP-facing request/response models (populated for the first time — `docs/SYSTEM_ARCHITECTURE.md` always said this would happen "once API-facing schemas are needed"), and CORS configuration for a local Vite dev server.

## Scope: which views get an API, and which don't

Per the scoping conversation, only the views with real data behind them get endpoints:

| View (Milestone 10 list) | API support |
|---|---|
| Station overview, induct/sortation, stow/jackpot | `/analytics/*` (Milestone 3's dbt metrics) |
| AI investigations | `/agents/flow-intelligence/*` (Milestone 5) |
| Digital-twin scenario runner | `/simulation/*` (Milestone 4) |
| RL policy comparison | `/rl/*` (Milestone 6) |
| Decision and audit history | `/decisions/*` (Milestones 7 & 9) |
| High-value processing, Pick & Stage, dispatch waves, returns | **Not built** — Cycle 2 doesn't exist (no domain model, no events); there is nothing for an endpoint to read |

## Security boundaries specific to exposing this over HTTP

Two things that were fine for a trusted local CLI script become real risks once reachable over the network, and are handled deliberately, not by accident:

1. **No arbitrary filesystem path from an HTTP caller.** `scripts/run_simulation.py`/`scripts/train_rl_policy.py` accept a free-form `--scenario` path because invoking them is a trusted local action. `POST /simulation/run`, `POST /rl/evaluate`, `POST /decisions`, and `POST /decisions/{id}/observe-outcome` instead take a `scenario` **filename**, resolved only against the shipped-scenarios directory by `app/simulation/config.py::resolve_shipped_scenario_path` — which calls `Path(filename).name` before the lookup, stripping any directory-traversal attempt, so `"../../../../etc/passwd"` resolves to looking for a file literally named `passwd` *inside* the scenarios directory (and fails to find it), never reading the real file. Verified with a dedicated test (`tests/simulation/test_config.py`, `tests/api/test_simulation.py`).
2. **No arbitrary DuckDB path from an HTTP caller either.** Every `/analytics/*` endpoint and `POST /agents/flow-intelligence/run` always reads the server-configured DuckDB file (`app/db/duckdb.py::resolve_duckdb_path`) — there is no `duckdb_path` field anywhere in `app/schemas/`. Even a read-only DuckDB connection to a caller-supplied path is an unnecessary arbitrary-file-access surface on a network-reachable endpoint; the CLI equivalents keep their explicit-path flexibility since they're trusted local invocations, not HTTP endpoints.
3. **CORS is a narrow, explicit allow-list** (`Settings.cors_allowed_origins`, default `http://localhost:5173`), not a wildcard — this is a local-first, single-operator tool, not a public multi-tenant service.

## Endpoints

### `/analytics` — read-only, Milestone 3 metrics

| Method | Path | Notes |
|---|---|---|
| GET | `/analytics/jackpot-volume` | |
| GET | `/analytics/wips` | |
| GET | `/analytics/induct-throughput` | |
| GET | `/analytics/stow-throughput` | |
| GET | `/analytics/parcel-dwell-time` | |

All five return **503** if the dbt pipeline hasn't been run against the configured DuckDB file yet (a clean, documented state for a frontend to render "not built yet," not a raw 500).

### `/agents/flow-intelligence` — the AI investigations view

| Method | Path | Notes |
|---|---|---|
| GET | `/agents/flow-intelligence/executions` | List, most recent first |
| GET | `/agents/flow-intelligence/executions/{id}` | 404 if unknown |
| POST | `/agents/flow-intelligence/run` | Runs the real agent with `OllamaProvider` — never `FakeLLMProvider`, which is test-only. If Ollama isn't reachable, `AgentExecutor`'s existing, already-tested fallback returns deterministic findings with `interpretation_error` set — this endpoint adds no new failure-handling logic. |

**A real nuance found while building this**: when the LLM step falls back, `AgentExecutor` (Milestone 5) marks the execution `FAILED` and records `error`, but never writes the fallback output into the persisted row's `output` column — only a successful run does that. `POST .../run`'s response therefore always reflects the actual in-memory result (`output.model_dump()`), not only whatever happened to get persisted — otherwise a caller hitting the fallback path would see `output: null` despite a real, non-fabricated result having been computed. This wasn't changed in `app/orchestration/` itself (out of scope for an API-layer session); the API route compensates instead.

### `/simulation` — the digital-twin scenario runner view

| Method | Path | Notes |
|---|---|---|
| GET | `/simulation/scenarios` | Lists shipped scenario files (name, description) |
| POST | `/simulation/run` | Body: `{"scenario": "<filename>", "seed": <optional override>}`. Runs synchronously, returns a summary (event count, per-event-type counts, `source_kind: "simulated"`) — never the raw event list, and never writes to disk (unlike `scripts/run_simulation.py`'s Parquet export; an HTTP endpoint shouldn't have an uncontrolled file-write side effect). |

### `/rl` — the RL policy-comparison view

| Method | Path | Notes |
|---|---|---|
| POST | `/rl/evaluate` | Body: `{"scenario": ..., "seeds": [...], "policies": [...]}`. Only `"static_baseline"`/`"rule_based_baseline"` are valid policy names (422 otherwise) — the trained PPO policy is deliberately not exposed here; there's no safe, generic way to accept an arbitrary model file path from an HTTP caller, and Milestone 6/7's own honest finding is that PPO isn't demonstrably better anyway. |

### `/decisions` — the decision/audit history view, and the one place the frontend can drive the governance pipeline

| Method | Path | Notes |
|---|---|---|
| GET | `/decisions` | Optional `?status=` filter |
| GET | `/decisions/{id}` | 404 if unknown |
| POST | `/decisions` | Proposes a decision — see `app/schemas/decisions.py::ProposeDecisionRequest` |
| POST | `/decisions/{id}/approve` | Body includes `approver_role` (`operator`/`supervisor`/`admin`) — **403** if that role isn't permitted for the decision's type (`app/security/rbac.py`), **409** if the record isn't `pending_approval` (already decided, or a shadow-mode record — see below) |
| POST | `/decisions/{id}/reject` | Same RBAC/state checks as approve |
| POST | `/decisions/{id}/observe-outcome` | **409** unless the record is `approved` |

`ProposeDecisionRequest.shadow: bool` (default `False`) proposes a decision that can never be approved, rejected, or have an outcome recorded — created with status `shadow` instead of `pending_approval`. No new check was needed for this: `approve_decision`/`reject_decision`/`observe_outcome` already only accept records starting from `pending_approval`/`approved` respectively, so `shadow` records are excluded automatically by the same existing guards.

**RBAC's honest limitation applies here too**: `approver_role` is a role the HTTP caller *claims*, checked against a fixed table — there is no login/session system behind it yet. A future, real auth layer would supply the verified role; the API doesn't pretend to have one now.

## Interactive docs

FastAPI auto-generates `/docs` (Swagger UI) and `/redoc` from the route/schema definitions above — run the server (`uvicorn app.main:app --reload`, or `docker compose up`) and open `http://localhost:8010/docs` (or `:8000` without the Docker port remap) to try any endpoint directly.

## A bonus found while building this: automatic HTTP span instrumentation

FastAPI 0.162 ships its own built-in OpenTelemetry integration (`fastapi/telemetry/`) — once `app/core/tracing.py::configure_tracing()` sets a real `TracerProvider` (which `app/main.py` does at import time), every HTTP request automatically gets a `SERVER`-kind span with standard semantic-convention attributes (`http.route`, `http.response.status_code`, etc.), with no extra instrumentation package installed or code written for it. This is in addition to, not instead of, the explicit spans `app/orchestration/runner.py` and `app/security/decision_service.py` already add around their own multi-step operations.
