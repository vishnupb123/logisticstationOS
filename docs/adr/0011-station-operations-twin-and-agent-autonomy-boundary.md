# ADR-0011: Full-day Station Operations Twin and the agent autonomy boundary

**Status**: Accepted (2026-11-08)

## Context

The project owner asked for the digital twin to reflect how a real delivery station's command centre works, for station-level metrics (DEA, sort compliance, on-time departure, ...), for daily truckfile updates driven by ferry status, and for an "autonomous" agentic system that learns situations, identifies risks and mitigates them.

Reference screenshots of real station tooling were shared locally to learn the workflow. They are **not** committed: they contain real employee logins and identifiers (CLAUDE.md hard rule 1), and `images/` is gitignored. Only generic process concepts were taken from them, never names, data or the tool's look:
- cycles whose pick start blocks further induct, so late volume rolls over;
- dwell and ageing by package status;
- receive with linehaul planned-vs-actual times;
- induct FPH, lost hours, no-read and multi-read rates;
- a stow WIP band and est. stow WIP compliance;
- outbound pick → stage → depart by stage-by wave, timely staged %, and routes at risk;
- labour shift plans.

The existing Cycle-1 twin (`app/simulation/model.py`) covers truck → stow only. Milestone 6 (RL) and Milestone 8 (predictive) depend on it byte for byte.

## Decision

1. **A separate full-day twin**, `app/simulation/station_ops/`, built beside the Cycle-1 model rather than on top of it.
   - Scope: linehaul arrival (with known delays) → receive → induct lines (scan defects, outages) → sort (missorts) → stow (WIP band) → cycle pick start / induct block / rollover → pick → stage → depart → delivery-attempt outcome.
   - Worker processes pull from queues, so capacity can change mid-run through a small, bounded set of levers (`Intervention`).
   - Every random attribute is pre-drawn per package and route, so two runs differing only by an intervention are identical up to that minute.
   - Same boundaries as ADR-0006: no PostgreSQL, no disk, and every snapshot is `source_kind="simulated"`. The API layer may read a truckfile from Postgres and pass it **in** as plain config; the twin never reads a database itself.
2. **The truckfile** (`app/inbound/`) is a plain planning table (`linehaul_trips`), refreshed daily through a `FerryStatusProvider` protocol.
   - The only implementation is a seeded synthetic provider.
   - A real operator feed is a future adapter. Scraping real third-party sites is deliberately out of scope for a public, synthetic-data repository.
3. **The Station Operations Agent** (`app/agents/station_ops/`) follows the three-function agent contract and runs a sense → simulate → score → learn → act loop.
   - **Sense**: rule-based detectors.
   - **Simulate and score**: counterfactual evaluation of candidate plans on the twin, scored with proposed weights.
   - **Learn**: a Postgres playbook of every evaluation, conditioned on the situation. Levers with a consistently negative record in that situation are skipped.
   - **Act**: depends on the mode, below.
4. **The autonomy boundary**:
   - `autopilot` mode **applies** plans to the in-memory twin only. There is no code path from it to anything else.
   - Anything framed as a real-world action becomes a `station_ops_mitigation` `DecisionRecord`, reaching the same policy engine (lever bounds), RBAC, approval state machine and observed-outcome guard as ADR-0009.
   - This keeps ADR-0009 intact: the agent is autonomous *inside the simulation*, and decision support *outside* it.
5. **Metrics are `proposed`.**
   - DEA uses the public definition (share of packages with a delivery attempt on or before the promised date).
   - OTD, sort compliance, timely staged, scan compliance and stow WIP compliance use generic definitions written out in `METRIC_DEFINITIONS`.
   - None is claimed as an organisation's validated formula.
6. **LLM layer**: a run whose LLM step fails is `degraded`, not `failed`. Its deterministic findings are complete. `failed` is reserved for evidence-gathering errors. The default local model is `qwen2.5:1.5b`, sized for an 8 GB laptop.

## Consequences

- There are two twins to keep in mind. The Cycle-1 twin stays the RL/predictive substrate; the station-ops twin is the operations and agent substrate. Merging them would mean re-validating Milestones 6 and 8.
- "Learning" is case-based and empirical over simulated episodes. It is not a trained model, and no claim is made about real-station effectiveness.
- `risk.py` still reports `simulation_only` blast radius. This is truthful today, because nothing acts on a live system.

## Revisit conditions

- A real ferry/operator status feed is integrated (needs a provider adapter plus a terms-of-use review).
- Any request to let the agent act outside the twin — that needs a new ADR revisiting ADR-0009, not a flag.
- Domain-owner validation of any `proposed` metric definition.
