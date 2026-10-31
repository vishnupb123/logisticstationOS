# StationOS — Engineering Handoff

**Purpose of this file**: the persistent, single source of truth for "where StationOS actually stands," written so a new engineering session (human or AI) can continue without this conversation's history. If something here conflicts with a doc in `docs/`, the more detailed doc wins for *content*; this file wins for *current status and what to do next*.

Last updated: 2026-10-31 (Milestone 1 completed this session).

---

## 1. Current milestone status

| Milestone | Status |
|---|---|
| 1 — Software foundation | ✅ **Complete** (this session) |
| 2 — Domain model and event infrastructure | Not started — **next** |
| 3–10 | Not started |

Full milestone definitions: `docs/ENGINEERING_ROADMAP.md` (rewritten this session to the ten-milestone structure given in the implementation-phase handoff — see §4 below).

## 2. What was true before this session

- One commit existed (`ef00dab`): the architecture/documentation set (README, CLAUDE.md, HANDOFF.md, `.gitignore`, `docs/` including ten ADRs).
- A backend skeleton existed on disk but was **uncommitted**: FastAPI app, settings, structured logging, PostgreSQL/DuckDB connectors, `/health` + `/health/ready`, Alembic wired to `Base.metadata` (no model migrations), a passing two-test pytest suite. No `docker-compose.yml`, no CI workflow, no `Dockerfile`.
- `backend/alembic/versions/` existed as an empty directory (untracked — git doesn't track empty dirs).

## 3. What changed this session (Milestone 1 closed out)

**Verified, not just assumed, correct:**
- Installed `backend` in a throwaway venv; `ruff check .` initially found one real issue (unsorted imports in `alembic/env.py`) — fixed with `ruff check --fix`, re-verified clean.
- `pytest` — 2 passed, before and after the lint fix.
- Built and ran the full Docker Compose stack (`docker compose up -d --build`), hit `/health` and `/health/ready` over HTTP, and got `{"status":"ok","dependencies":{"postgres":"ok","duckdb":"ok"}}` — a real Postgres connection and a real DuckDB file write, not a mock. Confirmed the DuckDB file landed in the host-mounted `./data/analytics/` directory, matching non-Docker behavior. Then tore the stack down (`docker compose down`) and removed the generated `.duckdb` file (it's gitignored, this was just test residue).

**Bug found and fixed before it shipped**: `app/db/duckdb.py` resolves its data path as `Path(__file__).resolve().parents[3]`, relying on `backend/` sitting directly under the repo root. A Dockerfile that copied only `backend/`'s contents into `/app` would collapse that path and silently write the DuckDB file to the wrong place inside the container. Fixed by building the image from the **repo root** as context (`docker-compose.yml` → `build.context: .`, `build.dockerfile: backend/Dockerfile`) and having the Dockerfile `COPY backend/ ./` into `/app/backend`, preserving the same nesting depth as local dev. Verified fixed by the DuckDB-file-location check above.

**Port collisions found and resolved**: this machine already has unrelated containers (`continuum-m0-postgres-1`, `continuum-m0-api-1`) bound to host ports 5432 and 8000. `docker-compose.yml` remaps StationOS to host ports **5433** (Postgres) and **8010** (API) — the internal Docker network still uses 5432/8000 between the `api` and `postgres` services, so this is purely a host-side convenience remap. **If your machine doesn't have this conflict, these numbers are arbitrary — change them back to 5432/8000 in `docker-compose.yml` if you prefer.**

**Files created:**
- `docker-compose.yml` (repo root) — Postgres + API services, healthcheck-gated startup, named volume for Postgres data, bind mounts for `./backend` (hot reload) and `./data` (DuckDB persistence).
- `backend/Dockerfile` — see the bug note above for why its `COPY`/`WORKDIR` structure matters.
- `.dockerignore` (repo root).
- `backend/.env.example` — placeholder values only, mirrors `Settings` defaults.
- `.github/workflows/ci.yml` — `ruff check` + `pytest` on push/PR to `main`, against a real `postgres:16-alpine` service container (not a mock), Python 3.12.
- `backend/alembic/versions/.gitkeep` — makes the empty migrations directory trackable.

**Files modified:**
- `backend/alembic/env.py` — lint fix only (import ordering), no behavior change.
- `README.md` — Docker Compose quickstart (Option A) alongside the existing venv quickstart (Option B); "Current status" section updated to "Milestone 1 complete"; noted the non-default ports and why.
- `CLAUDE.md` — status line updated; roadmap reference updated to ten milestones; commands section now mentions `docker compose up -d` and a stronger "actually run tests, report what happened" instruction.
- `docs/ENGINEERING_ROADMAP.md` — **rewritten** to the ten-milestone structure supplied in the implementation-phase handoff (see §4).
- `docs/adr/0007-rl-research-scope.md` — amended (not silently edited — amendment is dated and explained) to record that the project owner selected the first RL problem directly.
- `docs/RL_ENVIRONMENT_SPEC.md` — records the selected first RL problem (aisle-level stow capacity and workload balancing under variable inbound flow) and the candidate state/action variables that came with it; everything downstream of naming the problem (state/action/reward formalization) is still explicitly open.
- `docs/OPEN_QUESTIONS.md` — marks "which narrow RL problem" `resolved`; unblocks the reward-function question (no longer waiting on problem selection, still genuinely open).

**Nothing was rewritten that didn't need to be.** No domain models, events, agents, simulation, or RL code were added — that's Milestones 2–6, not this one.

## 4. Architectural/roadmap reconciliation performed

The implementation-phase handoff provided a more detailed ten-milestone plan than this repo's original nine-milestone (M0–M8) sketch. Per the handoff's own instruction ("do not silently change architecture... update the relevant architecture document... preserve traceability"):

- `docs/ENGINEERING_ROADMAP.md` was rewritten with a revision note at the top explaining the supersession and why (more detail, the original governance milestone split into two — M7 "agent/RL coordination" and M9 "governance and reliability" — and a new M8 "predictive intelligence" that the product vision always implied but never had its own milestone).
- No core architecture decision (the data stack, the layering, the governance stance) changed — this was a roadmap-detail reconciliation, not a stack or principle change, so no *new* ADR was warranted. The one decision that *was* newly made — the first RL problem — got a dated amendment to the existing ADR-0007 rather than a fresh ADR, since it's a scope-instance decision within an already-accepted ADR, not a new category of decision.

## 5. Environment observations (this machine, this session)

- Python 3.12.3, Docker 29.7.2, git 2.39.5 — all confirmed working by actually building and running the stack.
- `gh` CLI still not installed (unchanged from the architecture-phase handoff).
- **Two other unrelated Docker projects are running on this machine** (`continuum-m0-postgres-1` on 5432, `continuum-m0-api-1` on 8000) — not touched, not stopped; StationOS's Compose file was adjusted around them instead. Worth knowing if a future session also hits a port conflict and is tempted to investigate what's "wrong" — nothing is wrong, it's just a shared dev machine.

## 6. Known limitations

- CI has never actually run on GitHub yet (the workflow file is pushed in this session's commits, but no push/PR has triggered it as of this writing) — the "CI passes" claim in this file is based on running the same lint/test commands locally and via Docker Compose, not on a confirmed GitHub Actions run. Check the Actions tab after pushing to confirm.
- The Postgres named volume (`stationos_postgres_data`) and any local images built during verification remain on this machine; `docker compose down` was run (removes containers/network) but not `docker compose down -v` (would remove the volume too) — left in place since destroying a named volume is the kind of action to default against unless asked.
- `alembic/versions/` is now tracked but still has zero real migrations — don't mistake the `.gitkeep` for implementation progress.

## 7. Open questions (full register: `docs/OPEN_QUESTIONS.md`)

Highest-priority remaining:
1. Exact formulas for DEA, OTD, Sort Compliance, FPY, FSAF, Timely Staged, Route readiness — **blocked** on a domain-owner input; do not invent these (Milestone 3 depends on this only for the metrics it *can* define generically; the rest stay unimplemented).
2. Which LLM provider(s) implement the `LLMProvider` interface for real — Milestone 5 blocker.
3. RBAC role model for Layer 5 governance — Milestone 9 blocker (and partially Milestone 7).
4. Project license — unresolved, cosmetic but real.
5. (Resolved this session: which narrow RL problem — see §3/§4 above.)

## 8. Security considerations

No change to the governance stance (ADR-0009) or the public-repo safety checklist (`docs/SECURITY_AND_GOVERNANCE.md`) this session. New artifacts introduced (`docker-compose.yml`, `backend/.env.example`, CI workflow) were checked for secrets before commit — none present; `.env.example` has placeholder values identical to `Settings` defaults, not real credentials, and `.gitignore` already excludes real `.env` files.

## 9. Recommended next milestone

**Milestone 2 — Domain model and event infrastructure** (`docs/ENGINEERING_ROADMAP.md`). Start with Cycle 1 only (truck → induct → sort → stow), not the full entity list from the operational domain model at once. Build the typed event model and its duplicate/out-of-order/delayed/missing/replay handling with real tests before writing a synthetic event generator against it — the event model is the foundation every later milestone (analytics, twin, agents, RL) reads from, so it's worth getting right rather than fast.

## 10. Exact instructions for the next session

1. Read this file, then `docs/ENGINEERING_ROADMAP.md` Milestone 2, then `docs/OPERATIONAL_DOMAIN_MODEL.md` §2–3 (entities and Cycle 1 flow) and `docs/DATA_ARCHITECTURE.md` §"Event schema conventions".
2. Confirm the Milestone 1 foundation still works before building on it: `cd backend && pip install -e ".[dev]" && pytest && ruff check .`, and/or `docker compose up -d` + `curl http://localhost:8010/health/ready` (adjust the port if `docker-compose.yml` has since been changed back to the defaults).
3. Scope Milestone 2 to Cycle 1 entities/events only, per the roadmap's explicit non-goal boundary — resist building the full entity list in one pass.
4. Write tests for duplicate/out-of-order/delayed/missing/replay event handling *before or alongside* the ingestion code, not after — this is explicitly called out as needing comprehensive tests, not best-effort ones.
5. When Milestone 2 is done: update this file's status table and "last updated" date, note any new open questions or architectural findings the same way §3–§4 of this revision did, and leave the repo in a state where `pytest` and `ruff check .` both pass before ending the session.
