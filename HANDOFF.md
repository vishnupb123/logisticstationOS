# StationOS — Engineering Handoff

**Purpose of this file**: the persistent, single source of truth for "where StationOS actually stands," written so a new engineering session (human or AI) can continue without this conversation's history. If something here conflicts with a doc in `docs/`, the more detailed doc wins for *content*; this file wins for *current status and what to do next*.

Last updated: 2026-11-09 (live station runtime shared by every page; twin v2 with associates, HV cage, DSP drivers and RTS; five specialist agents; Station Assistant chat; 15 new live pages. All ten roadmap milestones remain complete.)

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

## 2. Latest session (2026-11-09): live station runtime, multi-agent orchestration, Station Assistant

The owner asked for several things:
- every screenshot feature implemented;
- the Cycle-1 twin integrated into Station Overview;
- an Associates tab;
- agents that are adaptive rather than static (OTD was 96.3% in every scenario);
- every page live;
- a chatbot that can get agents to fix things ("fix stow WIP");
- elaborated outbound: route prioritisation, high value, and a DSP coordination window with late drivers, wave moves, swipe-to-finish and live locations.

Built (ADR-0012, feature map in `docs/STATION_PROCESS_MODEL.md`):
- **Twin v2** (`backend/app/simulation/station_ops/`): individual associates (role, skill, live task, rebalancing, VET with a 45-min lead time from a finite flex pool), problem solve, the high-value cage (two custody scans; staging waits on handoff), bay capacity → jackpot, picklists (priority, sideline), carts and staging, DSP drivers (per-DSP lateness, no-shows with DSP auto-standby, notifications, sector traffic, standby reassignment, swipe-to-finish), stop-level delivery attempts, RTS, an ageing backlog with scrubs, progressively revealed ferry ETAs, seeded daily friction, and injectable disruptions. There are 6 presets, including the new `dispatch_disruption`. All actions are replayable `Intervention`s.
- **Views** (`views.py`): one computed view per page, plus search.
- **Five specialist agents + orchestrator** (`backend/app/agents/station_ops/`):
  - reflexes (wave reminders, sector rerouting, standbys, prioritisation, swipe, HV reinforcement);
  - robust counterfactual planning over belief futures (no oracle; OTD scored vs. the original plan);
  - flex-pool arbitration;
  - a situation-conditioned playbook;
  - online capacity learning;
  - bounded decision latency.
- **Live runtime** (`backend/app/runtime/`): `StationSession` threads plus a session manager, and the `/runtime/*` API (state, control, actions, recommendations approve/dismiss, chat, search).
- **Station Assistant** (`runtime/chat.py`): deterministic intents first; the local LLM only classifies into the same closed intent set.
- **Frontend**:
  - shared 1 s live polling; session bar (clock, pause, speed, agent mode, new day); global cycle alert, search, and an assistant on every page;
  - new pages: Command Center (performance summary), Receive, Sort Overview, Stow & Buffers, Problem Solve, Package Summary (dwell, ageing, RTS, search), Outbound Overview (wave grid), Pick, Stage, Dispatch & DSPs (live map), High Value, Associates, Shift Plan, Station & Resources, Work Items, Agent Console, Assistant;
  - Station Overview now shows the live day plus a continuously replaying Cycle-1 hamper twin, above the analytics history.

Measured (seed 2, agents on autopilot, two belief futures):

| Scenario | DEA without agents | DEA with agents | OTD without agents | OTD with agents |
|---|---|---|---|---|
| Normal day | — | — | 98.8% | 100% |
| Induct line outage | 79.4% | 99.7% | — | — |
| Ferry disruption | 89.2% | 94.0% | — | — |
| Peak volume | 63.9% | 98.3% | 98.8% | 95.0% |
| Dispatch disruption | — | — | 73.8% | 91.2% |

OTD now varies by day and scenario; it is no longer a constant.

Honest trade-off: on peak days the agents extend pick start, buying +34 DEA points at the cost of timely-staged (100% → 80%) and OTD (98.8% → 95.0%). The score weights (proposed) decide that trade.

At high playback speeds, bounded decision latency makes the session pause while agents plan (the session bar shows "agents planning…"), so 60× is effectively slower on busy days.

Flaws found by running it, all fixed:
1. Agents acted hours late at fast playback, because wall-clock think time became simulated delay. Fixed by bounding decision latency.
2. Detectors used nameplate induct rates, so shortfalls were caught at 06:30 instead of 03:00. Fixed with online capacity learning.
3. A single absent stower collapsed DEA on unlucky seeds. Fixed with a labor-plan buffer.
4. The HV handoff with one associate bottlenecked staging. Fixed by staffing 2 HV associates.
5. The stow WIP band flagged healthy days. The band is now a proposed 0.5–10 min.
6. Reminder spam in the logs. Reminders are now batched.
7. Small mobile overflow. Fixed.

Verification: backend 269 tests; Playwright 40 tests (every route plus live flows: new day, chat acting, dispatch actions, pick prioritisation, scrub, copilot approval, truckfile → live day); screenshots in light, dark and phone layouts.

## 2a. Previous session (2026-11-08): Station Operations, the agentic loop, and the LLM fix

The project owner shared screenshots of real station command-centre tooling in `images/`. They asked for:
- the twin and the UI to be modelled on how such a station works;
- station metrics (DEA, sort compliance, OTD, ...);
- a daily truckfile updated from ferry status;
- an agentic system that learns situations and mitigates risks;
- a fix for the failing AI investigations.

**The screenshots are never committed.** They contain real employee logins and identifiers (hard rule 1), and `images/` is gitignored. Only generic process concepts were taken from them; see ADR-0011.

Built (ADR-0011):
- **Station Operations Twin** (`backend/app/simulation/station_ops/`): a full-day, package-level SimPy model covering the whole flow.
  - Flow: linehauls with ferry delays → doors/unload → induct lines (no-read/multi-read rework, outages) → sort (missorts, caught or left behind) → stow (WIP band) → cycle pick start, which blocks induct so late volume rolls over → pick → stage → depart (driver lateness) → delivery attempt (late routes run out of driver hours).
  - Five presets.
  - Mid-run levers: add stowers or pickers, open a spare induct line, extend pick start (capped at 45 min), prioritise late linehaul volume.
  - Deterministic per seed; ~0.2 s per simulated day.
  - Metrics, all `proposed`: DEA, OTD, sort compliance, timely staged, scan compliance, est. stow WIP compliance, induct FPH, stow PPH, lost hours.
- **Truckfile** (`backend/app/inbound/`, table `linehaul_trips`): daily creation plus ferry-status refresh through `FerryStatusProvider`. The only implementation is a seeded synthetic provider; there is no real-site scraping. Available in the UI, via the API, and as `scripts/refresh_truckfile.py` for cron.
- **Station Operations Agent** (`backend/app/agents/station_ops/`):
  - Sense: rule-based detectors (late linehaul → rollover, induct/stow capacity shortfall, line down, routes at risk of stage-by, WIP band, quality).
  - Simulate: counterfactual evaluation of candidate and compound plans (e.g. "+30 min pick start + 3 pickers").
  - Score: proposed weights.
  - Learn: playbook table `agent_playbook_entries`, conditioned on situation.
  - Act: `observe`, `advise`, or `autopilot` (applies to the twin only).
  - Persisted investigations send recommended plans to the approval queue as `station_ops_mitigation` decisions, with lever bounds in the policy engine, supervisor RBAC, and observed outcome re-run on fresh seeds.
- **Frontend**: Command Center (`/command`, with Overview, Inbound, Package summary, Outbound route grid and Agent decision log tabs), Inbound Truckfile (`/truckfile`), and Station Agent (`/agent`, executions, learned playbook, LLM status). Decision detail renders station-ops candidates and outcomes.

**The AI investigations "failure"** had two parts:
1. Ollama wasn't installed, so every run hit `Connection refused`.
2. The runner marked a run whose deterministic findings were complete as `failed`.

Fixes: Ollama installed with `qwen2.5:1.5b` (the new default, fits 8 GB RAM, short keep-alive). Such runs are now `degraded`; `failed` is reserved for evidence errors, and evidence errors no longer leave rows stuck in `running`. The Flow Intelligence Agent now completes against the real model (~9 s).

**Measured results** (seed 1, simulated):

| Scenario | DEA before | DEA with agent on autopilot |
|---|---|---|
| Induct line outage | 80.0% | 99.8% |
| Labor shortage | 70.9% | 99.8% |
| Peak volume | 69.2% | 99.5% |
| Ferry disruption | 88.0% | 93.7% |

Every run kept timely-staged at 100%. The ~730 packages still lost in the ferry disruption are on sailings that arrive after any allowed cutoff; the agent holds rather than over-extending.

**Flaws found by actually running it:**
1. Two concurrent line outages produced duplicate same-type risks, caught by the e2e console-error guard.
2. The playbook averaged lever scores across situations, so "extend pick start" scored after an extension was already applied made the agent stop extending early in later runs.

Both are fixed, with regression tests.

Verification:
- Backend: 233 tests.
- Playwright e2e: 21 tests, including the command-centre day, truckfile → simulate, and agent → approval → observed outcome.
- Screenshots checked in light, dark and phone layouts, with no horizontal overflow.

Run the stack with `ollama serve` (or `brew services start ollama`) alongside the backend and frontend.

## 2c. Previous session (2026-11-07): end-to-end live view and a flaw audit

The project owner ran the full stack and asked why they couldn't "see live changes" if the system mimics a station. They then asked for it to work end to end with enterprise-grade end-to-end metrics, and for a check of what wasn't working or wasn't implemented as planned.

**What "live" means here, honestly**: the operational views read the dbt analytics snapshot of the *synthetic* event log, which changes only when new synthetic events are ingested and the pipeline re-runs. Nothing about that was broken, but nothing in the UI showed a station *operating* either. The fix is a live **playback of the digital twin**, always badged "Simulated run" (ADR-0002/0006 unchanged).

Built:
- **`GET /simulation/live`** (SSE, `app/simulation/live.py`): steps the same SimPy model in sim-time increments and streams `LiveSnapshot` frames (funnel, stage WIP, utilization, hampers, cycle-time p50/p90 including true dock→stow, recent events). Bounded parameters, `MAX_FRAMES` cap, allow-listed scenarios, nothing persisted. Final counts are tested to equal `/simulation/run`.
- **`GET /analytics/end-to-end`**: the Cycle-1 funnel and per-stage cycle times from `curated_parcel_lifecycle`.
- **Frontend**: a new **Live Operations** view (`/live`); Station Overview gained the end-to-end funnel, stage cycle times and 15s auto-refresh with "updated Ns ago"; a new app shell (grouped nav, live backend-health indicator, theme toggle, responsive down to phone width); KPI, funnel, meter, hamper-grid and page-header components; a pixel-accurate `TimeSeriesChart`.
- **Permanent Playwright e2e suite** (`frontend/e2e/`, 15 tests, `npm run test:e2e`) against the running stack.

**Real flaws found and fixed** (each reproduced before fixing):
1. **Running `pytest` destroyed the dev database.** `tests/conftest.py`'s session teardown ran `drop_all` against the same database the app uses, so every app table vanished mid-session and the API returned 500s. The suite now uses an auto-created `<db>_test` database; verified that the dev event count is identical before and after a full run.
2. **`/health/ready` reported DuckDB "unreachable" whenever a dashboard loaded.** The probe opened DuckDB read-write while the analytics routes held read-only connections, and DuckDB refuses mixed-configuration connections in one process. This was reproduced 3 out of 3 times with concurrent requests and is now fixed with a read-only probe; the regression test fails without the fix.
3. **Agent fallback output was never persisted** (the long-standing open question). Fixed at the root in `mark_failed`; the API and frontend workarounds are removed.
4. **The live stream never terminated**: SimPy's own `run(until=...)` marker keeps `env.peek()` finite. Termination is now a domain condition (trucks done and no parcels in flight).
5. UI: filled buttons lost their label on hover (`.button:hover` outranked the modifier class); proposing a decision left the user hunting for it in the list (it now navigates to the new decision).

Environment note: `/tmp`-based virtualenvs get partly cleaned by macOS. The backend venv now lives at `backend/.venv` (gitignored).

## 2a. Milestone 10, Part 2 — the frontend (2026-10-31)

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

*(At the time, no permanent frontend test suite was built. One now exists; see §2.)*

## 3. The scoping conversation's decisions, and how they played out

Recap from the prior session (`docs/ENGINEERING_ROADMAP.md` Milestone 10's write-up has the full detail): (1) API first, frontend second, in separate sessions — done, this session was the second one; (2) RBAC-gated actions reachable from the UI via a dev-mode role picker — built, see `src/components/RolePicker.tsx`; (3) a more-complete-than-minimal REST API — Part 1 already did this; (4) lightweight Vite + React + TypeScript SPA — done, no SSR framework, no heavier alternative considered once that was settled.

## 4. Known limitations

- **RBAC's limitation (Milestone 9) is unchanged and now surfaced in two places**: the API (`docs/API_REFERENCE.md`) and the UI itself (the role picker's own on-screen warning). Still no real login/session system — a role is claimed, not verified.
- **Cycle 2 has no UI, because it has no data.** High-value processing, Pick & Stage, dispatch waves, and returns were never built at any layer (domain model, events, analytics, or now frontend) — this isn't a frontend gap, it's upstream of the frontend entirely.
- **The e2e suite needs the stack running** and writes to the dev database (it proposes/approves a decision and runs the agent). It isn't wired into CI yet, because CI has no browser or frontend job.
- **Live Operations streams a simulated run, not operations.** There is still no live operational source; Station Overview moves only when the synthetic pipeline re-runs. A UI-triggered "ingest a new synthetic shift and rebuild analytics" action is a plausible next step, but it isn't built.
- **The decision-proposal form in the UI targets one specific scenario family** (`rl_stow_balancing.yaml`, three preset candidates matching `scripts/run_decision_demo.py`) — not a generic per-scenario candidate builder, since the API doesn't expose a scenario's aisle layout for the UI to build weights against generically. Documented in `frontend/src/views/DecisionHistory.tsx`'s own comment.

## 5. Open questions

Full register: `docs/OPEN_QUESTIONS.md`. New this session: should a permanent frontend test suite be built (leaning: yes, once the view set stabilizes); should `/rl/evaluate` ever expose a better-performing policy than the baselines (leaning: not yet, same reasoning as before). Reaffirmed: the `AgentExecutor` fallback-output-not-persisted gap now has two independent workarounds (API + frontend) rather than a root-cause fix — a real, if currently tolerable, smell worth revisiting if it recurs a third time.

## 6. Security considerations

The frontend adds no new backend trust boundary — it calls the exact same RBAC-checked, path-traversal-safe API Part 1 already built, with no parallel or weaker path. The dev-mode role picker is visibly, prominently labeled as not real authentication, in the UI a reviewer would actually see, not only in a doc they might not read. No real secrets, credentials, or data introduced. `.env.local` (the only place `VITE_API_BASE_URL` is actually set per-developer) is gitignored via Vite's own `*.local` pattern; only `.env.example` (placeholder values) is committed.

## 7. What a genuinely new phase of work could mean

The ten-milestone roadmap as originally scoped is done. Real, legitimate next steps exist, but none is "the next milestone" — picking one is a decision for whoever is directing the next session, not something to assume:

- **Wire the e2e suite into CI** (needs a frontend job with a browser, plus the seeded stack).
- **A UI-triggered synthetic ingest + analytics rebuild**, so the operational views can move on demand.
- **A second predictive candidate area** (Milestone 8's non-goal: five of six candidate areas were never attempted, two of which — route readiness, dispatch delay risk — still can't be, since they need Cycle 2 data).
- **Domain-randomized RL training** (Milestone 6's own open question — PPO's advantage vanished on a held-out scenario; training across varied seeds/parameters was never tried).
- **The rest of the agent roster** (`docs/AGENTIC_ARCHITECTURE.md` names Station Orchestrator, Planning, Investigation, Dispatch Intelligence, Reconciliation and Returns — only Flow Intelligence exists).
- **Cycle 2 itself** (Pick & Stage, dispatch, routes, waves, vans, returns) — the actual prerequisite for the Cycle-2-dependent predictive areas and frontend views that were skipped throughout, not a small addition.
- **A real risk/blast-radius model** beyond the Milestone 7 stub, and **real identity/auth** behind RBAC's claimed role — both explicitly flagged as stubs/gaps since Milestone 9, never silently left implicit.

## 8. Exact instructions for the next session

1. Read this file in full, then ask what's actually wanted — there's no default "next milestone" to fall back on anymore. §7 lists legitimate candidates, not a queue.
2. Confirm everything still works before changing anything: backend — `cd backend && pip install -e ".[dev,analytics,rl,predictive]" && ruff check .`; bring up Postgres, `alembic upgrade head` (four migrations), `pytest -q` (197 tests, against an auto-created `<db>_test` database). Frontend — `cd frontend && npm install && npm run build && npm run lint`, then with both servers up, `npm run test:e2e`. Then actually run both together (`uvicorn` + `npm run dev`) and click through at least one view for real — don't assume either side still works just because its own checks pass in isolation.
3. If frontend changes are in scope: read `frontend/README.md`'s two documented SVG gotchas before touching `src/components/charts/` — they're easy to reintroduce.
4. Whatever gets built next, follow the same discipline every milestone here did: verify for real (not "should work"), catch and honestly document real bugs rather than quietly working around them, update every relevant doc (not just this file), commit in small logical groups, and don't silently expand scope beyond what was actually asked for.
