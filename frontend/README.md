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

## Testing in a browser

This sandbox doesn't have `chromium-cli`; Playwright (a devDependency
here) with its own downloaded Chromium was used instead, driven by a
small one-off script per the `run` skill's `examples/playwright.md`
fallback pattern (launch headless Chromium, `goto`, interact, screenshot,
check `console --errors`-equivalent). That verification caught all of
the real bugs above — nothing here was verified by reading code alone.
No permanent test script/harness was committed this session (the
driver scripts were scratch, removed after use); if browser-based
verification becomes a recurring need, running `/run-skill-generator`
to capture it as a project skill is worth doing (per the `run` skill's
own recommendation) rather than re-improvising it each time.
