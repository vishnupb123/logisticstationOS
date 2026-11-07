# StationOS frontend — Milestone 10, Part 2

A lightweight Vite + React + TypeScript SPA (no SSR, no Node server of
its own) consuming the API built in Milestone 10 Part 1 — see
[`../docs/API_REFERENCE.md`](../docs/API_REFERENCE.md) for every
endpoint this talks to, and the root [`HANDOFF.md`](../HANDOFF.md) for
full project context.

## What's here

Seven views, each stating the source/status of what it shows
(synthetic vs. simulated — Milestone 10's exit criterion, see
`src/components/DataSourceBadge.tsx`):

- **Station Overview** (`/`) — key Cycle-1 metrics as stat tiles.
- **Induct & Sortation** (`/induct`) — induct throughput over time.
- **Stow & Jackpot** (`/stow`) — stow throughput by stower, jackpot volume.
- **AI Investigations** (`/investigations`) — Flow Intelligence Agent runs, evidence categories shown as-is.
- **Digital Twin Runner** (`/simulation`) — run a shipped scenario, see a summary.
- **RL Policy Comparison** (`/rl`) — compare the two baseline policies on a scenario.
- **Decisions & Audit** (`/decisions`) — the governance pipeline: propose, RBAC-checked approve/reject (via a clearly-labeled dev-mode role picker — **not real authentication**), observe outcome, shadow mode.

Cycle 2 views (high-value processing, Pick & Stage, dispatch waves,
returns) are **not built** — there's no backend data for them yet.

## Local development

```bash
npm install
cp .env.example .env.local   # adjust VITE_API_BASE_URL if needed (8000 direct, 8010 via Docker Compose)
npm run dev                  # http://localhost:5173
```

Needs Node 18+ (this project was built/verified against Node 20 via
`nvm`; the box's default `node` may be older — check `node --version`
before assuming `npm run dev` will even start).

Needs the backend running too (`cd ../backend && uvicorn app.main:app --reload`,
with Postgres up, migrations applied, and — for the analytics/AI
investigations views to show real data rather than a 503/empty state —
the synthetic generator + dbt pipeline run once; see the root
`README.md`'s "Running the analytics pipeline" section).

```bash
npm run build   # tsc -b && vite build — type-checks, then builds
npm run lint    # oxlint
```

## Design system

`src/index.css` defines the app's full design-token set (light/dark,
categorical/sequential/status palettes) from the `dataviz` skill's
validated reference palette — see that skill if extending the charts
in `src/components/charts/`.

**A real gotcha hit building the charts**: an inline SVG with
`viewBox="0 0 100 H"` and `preserveAspectRatio="none"` (used here so a
wide card gets a correctly-proportioned chart, not a square one)
stretches X and Y independently — any `<text>` inside that same
coordinate space renders visibly distorted/illegible, since glyphs get
stretched by the mismatched X/Y scale factors too. Axis labels are
therefore plain HTML positioned below the SVG (`.chart-axis-labels` in
`charts.css`), never SVG `<text>`. Also: an `<svg>` with a viewBox but
no explicit CSS `height` falls back to the viewBox's own intrinsic
aspect ratio to compute its rendered height from `width: 100%` — set
`style={{ height }}` explicitly, or it renders many times too tall.
Both were caught by actually rendering the page and looking at a
screenshot, not by reasoning about the code.

## Live Operations and the end-to-end metrics

`/live` (`src/views/LiveOperations.tsx`) consumes `GET /simulation/live`
through the browser's own `EventSource` (`src/api/live.ts`, no extra
dependency): the twin is played back frame by frame, so you can watch
trucks arrive and parcels move through induct → sort (or jackpot) →
stow. Frames update the KPIs, end-to-end funnel, stage cycle-time table,
utilization meters, WIP and cumulative time series, hamper heat grid and
event stream. It is always badged **Simulated run**.

Station Overview shows the same end-to-end shape for the synthetic
operational data (`GET /analytics/end-to-end`) and polls every 15s,
with a visible "Updated Ns ago". Those numbers change only when new
synthetic events are ingested and the pipeline (export → `dbt run`)
re-runs. That is the honest answer to "why doesn't the overview move
on its own?": there's no live operational source behind it, by design.

`src/components/charts/TimeSeriesChart.tsx` measures its own width
(ResizeObserver) and renders in true pixel coordinates, so neither SVG
gotcha above applies to it and its SVG `<text>` ticks are safe. Prefer
it for new time-series charts.

## End-to-end tests

`e2e/` is a permanent Playwright suite (15 tests) that runs against the
**running** stack, with no mocks: shell and health, every route's
data-source badge, overview metrics, live-run progression and
completion, agent fallback findings surviving a reload, and RBAC
(operator refused with 403, supervisor approves). Any browser console
error fails a test unless that test explicitly allows it.

```bash
# backend on :8010 and `npm run dev` on :5173 first, then:
npx playwright install chromium   # once
npm run test:e2e                  # E2E_BASE_URL overrides http://localhost:5173
```

The suite writes to the dev database (it proposes and approves a
decision, and runs the agent).

## Testing in a browser

This sandbox doesn't have `chromium-cli`; Playwright (a devDependency
here) with its own downloaded Chromium was used instead, driven by a
small one-off script per the `run` skill's `examples/playwright.md`
fallback pattern (launch headless Chromium, `goto`, interact, screenshot,
check `console --errors`-equivalent). That verification caught all of
the real bugs above — nothing here was verified by reading code alone.
The repeatable part of that now lives in `e2e/` (above). For a one-off
visual check (a screenshot to look at), a scratch Playwright script is
still the quickest route.
