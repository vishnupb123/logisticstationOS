# StationOS — Engineering Handoff

**Purpose of this file**: the persistent, single source of truth for "where StationOS actually stands," written so a new engineering session (human or AI) can continue without this conversation's history. If something here conflicts with a doc in `docs/`, the more detailed doc wins for *content*; this file wins for *current status and what to do next*.

Last updated: 2026-10-31 (Milestone 10, Part 2 — the React frontend — completed this session. **All ten roadmap milestones are now complete.**)

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
| 10 — Operational command centre (Part 1: API, Part 2: frontend) | ✅ **Complete, both parts** |

**There is no "next milestone" queued.** `docs/ENGINEERING_ROADMAP.md`'s original ten-milestone sequence is fully delivered. §9 below discusses what a genuinely new phase of work could mean — don't assume one without asking.

## 2. What was built this session (Milestone 10, Part 2 — the frontend)

**`frontend/`** — a Vite + React 19 + TypeScript SPA (no SSR, no Node server of its own), per the scoping conversation's decision: React Router for the seven views, TanStack Query for server state, inline SVG charts (no charting library dependency). Design tokens (`src/index.css`) come from the `dataviz` skill's validated reference palette.

**Seven views**, each with a `DataSourceBadge` ("Synthetic data" / "Simulated run," never "live" — Milestone 10's exit criterion, satisfied literally):
- Station Overview, Induct & Sortation, Stow & Jackpot — read `/analytics/*`.
- AI Investigations (+ detail) — lists/runs the Flow Intelligence Agent, evidence categories shown with fixed-color badges, never flattened to prose.
- Digital Twin Scenario Runner — runs a shipped scenario, shows a real summary.
- RL Policy Comparison — evaluates the two baseline policies (never PPO) against a scenario, as small-multiple bar charts (never one dual-axis chart for metrics of different scale/unit).
- Decisions & Audit History (+ detail) — the full governance pipeline: propose, RBAC-checked approve/reject via the agreed **dev-mode role picker** (prominently labeled in the UI itself — not just in docs — as not real authentication), observe outcome, shadow mode (visibly distinct status, no approval form rendered for it at all).

**Four real bugs found and fixed by actually running the app in a browser** — this sandbox has no `chromium-cli`; Playwright with a downloaded Chromium was used instead (see `frontend/README.md`'s "Testing in a browser" section for the exact approach). None of these were visible from reading the code:
1. An SVG chart with a `viewBox` but no explicit CSS `height` rendered ~9x too tall (the browser fell back to the viewBox's own intrinsic aspect ratio to compute height from `width: 100%`).
2. SVG `<text>` inside a `preserveAspectRatio="none"`-stretched coordinate space rendered as distorted, illegible glyphs — axis labels were moved to plain HTML below the SVG.
3. Clicking into a just-run agent execution's detail page showed "no findings," even though real deterministic findings were computed — because (per Part 1's own documented finding) `AgentExecutor`'s LLM-fallback path never persists its output to the audit row, and the detail page's `GET` honestly reflected that. Fixed by seeding the React Query cache with the `/run` mutation's actual response, so the real result shows immediately after running, while a later page reload still honestly shows what's actually persisted.
4. The RL Policy Comparison view defaulted to the alphabetically-first scenario (`delayed_inbound_trucks`) rather than the `rl_`-tuned family — silently comparing policies on a scenario Milestone 6 already documented as never producing a meaningful difference between them.

**No permanent frontend test suite was built.** The Playwright verification was scratch (a handful of one-off driver scripts), removed after use — not committed. `frontend/README.md` flags this and suggests `/run-skill-generator` if browser-based verification becomes a recurring need, per the `run` skill's own recommendation.

## 3. The scoping conversation's decisions, and how they played out

Recap from the prior session (`docs/ENGINEERING_ROADMAP.md` Milestone 10's write-up has the full detail): (1) API first, frontend second, in separate sessions — done, this session was the second one; (2) RBAC-gated actions reachable from the UI via a dev-mode role picker — built, see `src/components/RolePicker.tsx`; (3) a more-complete-than-minimal REST API — Part 1 already did this; (4) lightweight Vite + React + TypeScript SPA — done, no SSR framework, no heavier alternative considered once that was settled.

## 4. Known limitations

- **RBAC's limitation (Milestone 9) is unchanged and now surfaced in two places**: the API (`docs/API_REFERENCE.md`) and the UI itself (the role picker's own on-screen warning). Still no real login/session system — a role is claimed, not verified.
- **Cycle 2 has no UI, because it has no data.** High-value processing, Pick & Stage, dispatch waves, and returns were never built at any layer (domain model, events, analytics, or now frontend) — this isn't a frontend gap, it's upstream of the frontend entirely.
- **No frontend test suite.** Regressions in the four bug categories found this session (or new ones) won't be caught automatically — see §2's last paragraph and `docs/OPEN_QUESTIONS.md`.
- **The decision-proposal form in the UI targets one specific scenario family** (`rl_stow_balancing.yaml`, three preset candidates matching `scripts/run_decision_demo.py`) — not a generic per-scenario candidate builder, since the API doesn't expose a scenario's aisle layout for the UI to build weights against generically. Documented in `frontend/src/views/DecisionHistory.tsx`'s own comment.
- The tests-vs-dev-database footgun (backend) is unchanged — not hit this session (frontend work needed the backend up but didn't run the backend's own pytest suite in the same session as manual testing).

## 5. Open questions

Full register: `docs/OPEN_QUESTIONS.md`. New this session: should a permanent frontend test suite be built (leaning: yes, once the view set stabilizes); should `/rl/evaluate` ever expose a better-performing policy than the baselines (leaning: not yet, same reasoning as before). Reaffirmed: the `AgentExecutor` fallback-output-not-persisted gap now has two independent workarounds (API + frontend) rather than a root-cause fix — a real, if currently tolerable, smell worth revisiting if it recurs a third time.

## 6. Security considerations

The frontend adds no new backend trust boundary — it calls the exact same RBAC-checked, path-traversal-safe API Part 1 already built, with no parallel or weaker path. The dev-mode role picker is visibly, prominently labeled as not real authentication, in the UI a reviewer would actually see, not only in a doc they might not read. No real secrets, credentials, or data introduced. `.env.local` (the only place `VITE_API_BASE_URL` is actually set per-developer) is gitignored via Vite's own `*.local` pattern; only `.env.example` (placeholder values) is committed.

## 7. What a genuinely new phase of work could mean

The ten-milestone roadmap as originally scoped is done. Real, legitimate next steps exist, but none is "the next milestone" — picking one is a decision for whoever is directing the next session, not something to assume:

- **A permanent frontend test suite**, once the view set has had a chance to prove stable (§5).
- **A second predictive candidate area** (Milestone 8's non-goal: five of six candidate areas were never attempted, two of which — route readiness, dispatch delay risk — still can't be, since they need Cycle 2 data).
- **Domain-randomized RL training** (Milestone 6's own open question — PPO's advantage vanished on a held-out scenario; training across varied seeds/parameters was never tried).
- **The rest of the agent roster** (`docs/AGENTIC_ARCHITECTURE.md` names Station Orchestrator, Planning, Investigation, Dispatch Intelligence, Reconciliation and Returns — only Flow Intelligence exists).
- **Cycle 2 itself** (Pick & Stage, dispatch, routes, waves, vans, returns) — the actual prerequisite for the Cycle-2-dependent predictive areas and frontend views that were skipped throughout, not a small addition.
- **A real risk/blast-radius model** beyond the Milestone 7 stub, and **real identity/auth** behind RBAC's claimed role — both explicitly flagged as stubs/gaps since Milestone 9, never silently left implicit.

## 8. Exact instructions for the next session

1. Read this file in full, then ask what's actually wanted — there's no default "next milestone" to fall back on anymore. §7 lists legitimate candidates, not a queue.
2. Confirm everything still works before changing anything: backend — `cd backend && pip install -e ".[dev,analytics,rl,predictive]" && ruff check .`; bring up Postgres, `alembic upgrade head` (four migrations), `pytest -q` (190 tests). Frontend — `cd frontend && npm install && npm run build && npm run lint`. Then actually run both together (`uvicorn` + `npm run dev`) and click through at least one view for real — don't assume either side still works just because its own checks pass in isolation.
3. If frontend changes are in scope: read `frontend/README.md`'s two documented SVG gotchas before touching `src/components/charts/` — they're easy to reintroduce.
4. Whatever gets built next, follow the same discipline every milestone here did: verify for real (not "should work"), catch and honestly document real bugs rather than quietly working around them, update every relevant doc (not just this file), commit in small logical groups, and don't silently expand scope beyond what was actually asked for.
