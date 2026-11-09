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
| GET | `/analytics/end-to-end` | Cycle-1 funnel (inducted / exception / sorted / ever-jackpotted / stowed) plus count, avg, p50, p90 for induct→sort, sort→stow and induct→stow, from `curated_parcel_lifecycle`. Status: `proposed`. |

All six return **503** if the dbt pipeline hasn't been run against the configured DuckDB file yet (a clean, documented state for a frontend to render "not built yet," not a raw 500).

### `/agents/flow-intelligence` — the AI investigations view

| Method | Path | Notes |
|---|---|---|
| GET | `/agents/flow-intelligence/executions` | List, most recent first |
| GET | `/agents/flow-intelligence/executions/{id}` | 404 if unknown |
| POST | `/agents/flow-intelligence/run` | Runs the real agent with `OllamaProvider` — never `FakeLLMProvider`, which is test-only. If Ollama isn't reachable, `AgentExecutor`'s existing, already-tested fallback returns deterministic findings with `interpretation_error` set — this endpoint adds no new failure-handling logic. |

**Fallback output is persisted** (fixed 2026-11-07): when the LLM step falls back, `AgentExecutor` marks the execution `FAILED`, records `error`, *and* stores the deterministic fallback output on the row (`repository.mark_failed(..., fallback_output=...)`). `GET .../executions/{id}` therefore returns the same findings `POST .../run` did, including after a reload. Before this fix the output was dropped, and both this route and the frontend carried workarounds; both are removed.

### `/simulation` — the digital-twin scenario runner view

| Method | Path | Notes |
|---|---|---|
| GET | `/simulation/scenarios` | Lists shipped scenario files (name, description) |
| POST | `/simulation/run` | Body: `{"scenario": "<filename>", "seed": <optional override>}`. Runs synchronously, returns a summary (event count, per-event-type counts, `source_kind: "simulated"`) — never the raw event list, and never writes to disk (unlike `scripts/run_simulation.py`'s Parquet export; an HTTP endpoint shouldn't have an uncontrolled file-write side effect). |

| GET | `/simulation/live?scenario=<filename>&seed=&step_seconds=30&frame_interval_ms=200` | **Server-Sent Events** stream of `LiveSnapshot` frames (`event: snapshot`), then `event: end`. Each frame: simulated clock, cumulative funnel counts, current WIP per stage, induct/stower utilization, per-aisle hamper levels, cycle-time stats (dock→stow, induct→sort, sort→stow, induct→stow) and the events emitted since the previous frame. Same shipped-scenario allow-list as `/run` (404 on unknown or traversal input). `step_seconds` is bounded to 5–600 and `frame_interval_ms` to 0–2000 (422 otherwise), and the stream is capped at `MAX_FRAMES` (2000), so it always terminates. Nothing is persisted, and every frame carries `source_kind: "simulated"`. Final counts match `/run` for the same scenario and seed (tested). |

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

### `/station-ops`, `/inbound`, `/agents/station-ops`, `/llm` — Station Operations (2026-11-08, ADR-0011)

- `GET /station-ops/presets` — the fixed allow-list of scenario presets (`normal_day`, `ferry_disruption`, `induct_line_outage`, `labor_shortage`, `peak_volume`). An unknown name gets a 404 and is never treated as a path.
- `GET /station-ops/metric-definitions` — every metric's formula and `proposed` status, plus the agent's score weights and lever limits.
- `POST /station-ops/run-day` `{preset, seed, source: preset|truckfile, ofd_date?, interventions[]}` — a one-shot what-if run of the full day. Interventions are checked against the policy engine's lever bounds (422 if out of bounds).
- `GET /station-ops/live?preset&seed&mode=observe|advise|autopilot&source&ofd_date&learn&step_minutes&frame_interval_ms` — an SSE stream.
  - Emits `event: frame` `{snapshot, agent: {risks, new_actions}}` until every route has departed, then `event: end`.
  - Bounded by `MAX_FRAMES`.
  - `autopilot` applies plans to the in-memory twin only. With `learn=true`, evaluations are written to the playbook.
- `GET /inbound/truckfile?ofd_date` and `POST /inbound/truckfile/refresh` `{ofd_date, weather?, seed}` — the daily job: create the day's synthetic truckfile if missing, check every ferry sailing, and write revised ETAs. It is also available as `scripts/refresh_truckfile.py`.
- `POST /agents/station-ops/run` `{preset, seed, source, ofd_date?, until_minute, propose_decisions}` — a persisted Station Operations Agent investigation.
  - Records the agent's evaluations to the playbook.
  - Creates one `station_ops_mitigation` decision (`pending_approval`) per recommended plan.
  - Returns `{execution, decision_ids}`. The execution status is `completed`, or `degraded` if the LLM was unavailable; deterministic output is complete either way.
- `GET /agents/station-ops/executions[/{id}]` and `GET /agents/station-ops/playbook` (learned per-situation lever statistics).
- `GET /llm/status` — whether the configured Ollama model is reachable.
- `POST /decisions/{id}/observe-outcome` — `scenario` is now optional. It is ignored for `station_ops_mitigation`, which re-runs the twin with the approved plan on fresh seeds (`kind: simulated_rerun_on_fresh_seeds`).

### `/runtime` — live station runtime (2026-11-09, ADR-0012)

- `GET /runtime/sessions` and `POST /runtime/sessions` `{preset, seed?, mode, speed, source: preset|truckfile, ofd_date?}` — start a live simulated day. The new session becomes the default; with no seed, a fresh random day is drawn.
- `GET /runtime/sessions/{id|default}/state` — the snapshot, every page view, and agent risks, actions and pending recommendations.
- `POST /runtime/sessions/{id}/control` `{paused?, speed?, mode?: observe|advise|autopilot}`.
- `POST /runtime/sessions/{id}/actions` — an `Intervention` applied to the *simulated* station.
  - Bounded by `LEVER_LIMITS` (422 if outside); `inject_disruption` kinds and magnitudes are capped.
  - Actions include `add_stowers` / `add_pickers` (VET), `move_associates`, `open_induct_line`, `extend_cutoff`, `prioritize_route`, `sideline_route`, `unsideline_route`, `move_route_wave`, `notify_drivers` (route, late, all, `params.routes`, or `params.sector` + `leave_early_minutes`), `reassign_standby`, `notify_swipe_finish`, `resequence_unload`, `priority_late_linehauls`, and `start_scrub`.
- `POST /runtime/sessions/{id}/recommendations/{action_id}/approve|dismiss` — copilot approvals (409 if not pending).
- `POST /runtime/sessions/{id}/chat` `{message}` → `{reply, intent, actions, data, understood_by}`; `GET .../chat` returns the history.
- `GET /runtime/sessions/{id}/search?q=` — a package, container (route) or associate.

## Interactive docs

FastAPI auto-generates `/docs` (Swagger UI) and `/redoc` from the route/schema definitions above — run the server (`uvicorn app.main:app --reload`, or `docker compose up`) and open `http://localhost:8010/docs` (or `:8000` without the Docker port remap) to try any endpoint directly.

## A bonus found while building this: automatic HTTP span instrumentation

FastAPI 0.162 ships its own built-in OpenTelemetry integration (`fastapi/telemetry/`) — once `app/core/tracing.py::configure_tracing()` sets a real `TracerProvider` (which `app/main.py` does at import time), every HTTP request automatically gets a `SERVER`-kind span with standard semantic-convention attributes (`http.route`, `http.response.status_code`, etc.), with no extra instrumentation package installed or code written for it. This is in addition to, not instead of, the explicit spans `app/orchestration/runner.py` and `app/security/decision_service.py` already add around their own multi-step operations.
