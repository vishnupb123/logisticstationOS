# StationOS — Engineering Handoff

**Purpose of this file**: the persistent, single source of truth for "where StationOS actually stands," written so a new engineering session (human or AI) can continue without this conversation's history. If something here conflicts with a doc in `docs/`, the more detailed doc wins for *content*; this file wins for *current status and what to do next*.

Last updated: 2026-10-31 (Milestone 10, Part 1 — the API layer — completed this session).

---

## 1. Current milestone status

| Milestone | Status |
|---|---|
| 1 — Software foundation | ✅ Complete |
| 2 — Domain model and event infrastructure (Cycle 1 slice) | ✅ Complete |
| 3 — Data engineering and analytics | ✅ Complete |
| 4 — Digital twin | ✅ Complete |
| 5 — Agentic AI system | ✅ Complete |
| 6 — Reinforcement-learning environment | ✅ Complete |
| 7 — Agent and RL coordination | ✅ Complete |
| 8 — Predictive intelligence | ✅ Complete |
| 9 — Governance and reliability | ✅ Complete |
| 10 — Operational command centre | 🟡 **Part 1 (API layer) complete this session.** Part 2 (React/TypeScript frontend) **not started.** |

Full milestone definitions: `docs/ENGINEERING_ROADMAP.md`.

## 2. The scoping conversation, and what it decided

Before any frontend code was written, the project owner had an explicit scoping conversation (prompted by three prior sessions' deferrals). Four decisions came out of it:

1. **Build the complete backend API first, then the frontend, in a separate session.** This is why this session built Part 1 only — no React/TypeScript code exists yet.
2. **The decision-governance pipeline's actions (approve/reject) should be reachable from the eventual UI**, via an explicit "dev-mode role picker" (no real login system) rather than staying read-only.
3. **Build a more complete REST API now**, not just the minimal slice the first frontend cut needs — anticipating that a real role-picker UI and other future consumers will want it.
4. **Lightweight Vite + React + TypeScript SPA** (no SSR) for the eventual frontend, once Part 2 starts — noted here for when that session begins, not acted on yet.

Views with Cycle 2 data requirements (high-value processing, Pick & Stage, dispatch waves, returns) were **not** built — Cycle 2 doesn't exist (no domain model, no events), so there's nothing for an endpoint to read. This wasn't a separate scoping decision to re-litigate; it falls out of what data actually exists.

## 3. What was built this session (Milestone 10, Part 1)

**`backend/app/schemas/`** (new package — populated for the first time; `docs/SYSTEM_ARCHITECTURE.md` had long said this would happen "once API-facing schemas are needed"): `decisions.py`, `simulation.py`, `rl.py`, `agents.py` — HTTP-facing request/response models, kept distinct from each module's own internal domain Pydantic models.

**`backend/app/api/routes/`** gained five routers:
- `analytics.py` — the five Milestone 3 metrics, read-only, 503 if the dbt pipeline hasn't been run.
- `agents.py` — list/get/run Flow Intelligence Agent executions. `POST .../run` uses the real `OllamaProvider` (never `FakeLLMProvider` — that stays test-only); if Ollama isn't reachable, the existing, already-tested fallback path handles it.
- `simulation.py` — list shipped scenarios, run one synchronously and get a summary (never the raw event list, never a disk write).
- `rl.py` — evaluate the two baseline policies (never the trained PPO policy) against a scenario.
- `decisions.py` — list/get/propose/approve/reject/observe-outcome. The same RBAC checks and state-machine guards as the Python API — no separate code path.

**Two HTTP-specific security boundaries**, deliberate and tested, not incidental: no endpoint accepts a free-form filesystem path (`app/simulation/config.py::resolve_shipped_scenario_path` resolves a filename against a shipped-scenario allow-list, stripping any directory-traversal attempt) or a free-form DuckDB path (always the server-configured one). CORS is a narrow local-dev allow-list, not a wildcard.

**36 new tests** (154 → 190 total): `tests/api/` (29, across all five routers, including dedicated path-traversal-rejection tests), plus direct unit tests for `app/simulation/config.py`'s new helpers and `app/orchestration/repository.py::list_executions` (also new, needed for the agents API).

**Verified live, not just via `TestClient`**: ran the real server with `uvicorn`, and over real HTTP: listed scenarios, proposed a decision (real simulation-based candidate evaluation), had an `operator` get refused (403), had a `supervisor` approve it, ran the observed-outcome simulation, ran an RL evaluation, and listed agent executions. Full reference: `docs/API_REFERENCE.md`.

## 4. A real nuance found while building this

`AgentExecutor`'s LLM-fallback path (Milestone 5) marks an execution `FAILED` and records `error`, but never writes the fallback output into the persisted row's `output` column — only a successful run does that (`mark_completed`). `POST /agents/flow-intelligence/run` compensates by always returning the actual in-memory result, not relying solely on what got persisted — otherwise a caller hitting the fallback path would see `output: null` despite a real, non-fabricated result having been computed. **Not changed in `app/orchestration/` itself** — that would be revisiting Milestone 5's established, tested behavior, out of scope for an API-layer session. Tracked in `docs/OPEN_QUESTIONS.md` as a real but deliberately-deferred question.

## 5. Known limitations

- **Part 2 (the actual frontend) doesn't exist.** This session built the API it will consume, nothing more. Don't assume any UI exists when reasoning about "what Milestone 10 delivers."
- **RBAC's limitation from Milestone 9 applies identically over HTTP**: `approver_role` is a claimed role, not a verified identity — the API doesn't add (or pretend to add) authentication.
- **Only two RL policies are exposed via `/rl/evaluate`** (the baselines) — not the trained PPO policy, deliberately, for the same reason Milestones 6/7 never wired it into anything beyond its own evaluation report.
- **`/simulation/run` and `/rl/evaluate` are synchronous** — a large seed list or an expensive scenario blocks that request for its full duration (FastAPI runs sync `def` routes in a thread pool, so this doesn't block other requests, but the caller still waits). Request schemas cap seed-list length (`max_length=20`) as a basic guard; no async job queue was built, since that would be real new infrastructure for a need that hasn't shown up yet.
- The tests-vs-dev-database footgun from prior milestones is unchanged (hit and recovered the documented way twice during this session's manual testing).

## 6. Open questions

Full register: `docs/OPEN_QUESTIONS.md`. New this session: exact Part 2 frontend scope (which views ship first, is the dev-mode role picker in the first cut); whether `/agents/flow-intelligence/run` should ever support a `FakeLLMProvider` dev-mode flag (leaning: no); whether `AgentExecutor`'s fallback path should start persisting its output (unresolved, deliberately not decided this session). Unchanged: RBAC's claimed-role limitation; real risk/blast-radius model beyond the Milestone 7 stub; should the jackpot-risk prediction or the trained RL policy ever become agent/decision evidence (both still leaning: not yet).

## 7. Security considerations

Two new, deliberate boundaries specific to being HTTP-reachable (§3) — path-traversal protection and no-arbitrary-DuckDB-path — are documented in `docs/SECURITY_AND_GOVERNANCE.md`'s threat model table, not just implied by the code. CORS stays a narrow local-dev allow-list. The decision-governance pipeline's RBAC and audit guarantees are unchanged by being reachable over HTTP — the API calls the exact same `app/security/repository.py` functions, no parallel or weaker path was added. No new secrets, credentials, or real data introduced.

## 8. Recommended next steps

**Milestone 10, Part 2 — the React/TypeScript frontend.** Per the scoping conversation: a lightweight Vite + React + TypeScript SPA (no SSR), talking to the API built this session, including the explicit "dev-mode role picker" for RBAC-gated decision actions (clearly labeled as not real authentication). `docs/API_REFERENCE.md` is the menu of what's available to build views against. Views to build: station overview, induct/sortation, stow/jackpot (via `/analytics`), AI investigations (`/agents/flow-intelligence`), digital-twin scenario runner (`/simulation`), RL policy comparison (`/rl`), decision/audit history with approve/reject actions (`/decisions`). Cycle 2 views stay out of scope — there's still no data for them.

## 9. Exact instructions for the next session

1. Read this file, then `docs/API_REFERENCE.md` in full, then `docs/ENGINEERING_ROADMAP.md` Milestone 10's Part 1 write-up (so the actual delivered API shape is understood before designing against it, not assumed).
2. Confirm Milestones 1–9 and Part 1 still work: `cd backend && pip install -e ".[dev,analytics,rl,predictive]" && ruff check .`; bring up Postgres, `alembic upgrade head` (four migrations), `pytest -q` (190 tests). Also smoke-test the real server once: `uvicorn app.main:app --reload`, hit `/docs`, try a couple endpoints for real — don't assume the API still works just because the tests pass.
3. Scope Part 2 concretely before writing frontend code: which views ship first (all seven API-backed ones, or a smaller first cut), and whether the dev-mode role picker is in that first cut or a fast-follow.
4. Set up the frontend project (`frontend/`, currently a placeholder directory) — Vite + React + TypeScript, pointed at the API's CORS-allowed origin (`http://localhost:5173` is the default `Settings.cors_allowed_origins` entry; keep them in sync if the dev port changes).
5. Every view must state the source/status of what it shows (Milestone 10's exit criterion) — `source_kind: "simulated"` is already in the `/simulation/run` and `/rl/evaluate` response shapes for exactly this reason; carry that labeling into the UI, don't drop it.
6. When Part 2 is done (or substantially progressed): update this file's status table and date, update `docs/ENGINEERING_ROADMAP.md`'s Milestone 10 entry to reflect both parts complete, and update `docs/OPEN_QUESTIONS.md` for anything resolved or newly found.
