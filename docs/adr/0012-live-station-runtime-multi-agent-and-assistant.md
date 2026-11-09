# ADR-0012: Live station runtime, multi-agent orchestration, and the Station Assistant

**Status**: Accepted (2026-11-09). Extends ADR-0011; does not revisit ADR-0009.

## Context

The project owner asked for several things:
- every page to be live and adaptive (no static tabs);
- every process concept from their reference screenshots to be implemented;
- associate, high-value and outbound pick/stage pages, and a DSP coordination window covering late drivers, wave moves, swipe-to-finish and live locations;
- the Cycle-1 twin integrated into Station Overview;
- less static agent decision-making (OTD read 96.3% in every scenario);
- a chatbot that answers questions and gets the agents to fix things.

ADR-0011's design gave each SSE stream its own private twin. No two pages could show the same day, and a chat command had nothing shared to act on.

## Decision

1. **A shared live runtime** (`app/runtime/session.py`).
   - One in-memory `StationSession` per simulated day, advanced by a background thread in simulated time.
   - Every page polls the same `/runtime/sessions/default/state`, which returns the snapshot plus all page views.
   - A new day gets a fresh random seed unless one is given, so no two days look the same.
   - At most 3 sessions run; nothing is persisted except the agents' playbook.
   - SimPy is not thread-safe, so all twin access happens under one RLock.
2. **Twin v2** (`app/simulation/station_ops/model.py`) models what the screenshots showed. All of it is synthetic, with generic names:
   - individual associates with roles, skill and live tasks;
   - problem solve, and a high-value cage with two custody scans;
   - bay capacity → jackpot;
   - picklists with priority and sideline;
   - carts and staging;
   - DSP drivers with lateness, no-shows, notifications, standbys, traffic, swipe-to-finish and positions on a fictional map;
   - stop-level delivery attempts, RTS and an ageing backlog with scrubs;
   - progressively revealed ferry ETAs;
   - seeded random daily friction (jams, scanner drift, traffic, weather);
   - injectable disruptions.

   Every action and disruption is a replayable `Intervention`.
3. **Five specialist agents under one orchestrator** (`app/agents/station_ops/loop.py`): Inbound, Sort & Stow, Outbound, Dispatch, and Quality & HV. Each cycle runs:
   - **sense**, using known information only;
   - **reflex**: cheap, low-risk coordination such as reminders, rerouting, standbys and prioritisation;
   - **plan**: robust counterfactual evaluation over K *belief futures* (counterfactual.py);
   - **arbitrate**: shares out the finite VET pool and avoids lever conflicts;
   - **act or recommend**: autopilot applies to the twin; copilot queues for a human; observe only reports;
   - **learn**: a situation-conditioned playbook.

   Two adaptive estimators keep the agents honest:
   - online capacity estimation from observed throughput under a standing queue;
   - bounded decision latency (the sim waits after 5 simulated minutes of agent "thinking").
4. **Information discipline is structural.**
   - Detectors see revealed ETAs, planned check-ins, and no-shows only once overdue.
   - Belief futures replay the *occurred* history exactly, drop unrevealed disruptions, resample unknown driver behaviour, and add ETA error.
   - OTD used for scoring is measured against the *original* wave plan, so moving a route can't game the metric.
5. **The Station Assistant** (`app/runtime/chat.py`).
   - A deterministic intent parser handles questions (answered from live state; numbers computed, never generated) and requests (routed to an agent goal or applied to the simulated station).
   - Only unmatched messages go to the local LLM, which may *classify* them into the same closed intent set, schema-restricted per ADR-0008.
   - "What if" requests are simulated and not applied.
6. **The autonomy boundary is unchanged (ADR-0009).**
   - Autopilot, chat and UI actions all act on the in-memory twin only.
   - API actions are bounded by `LEVER_LIMITS` and disruption caps.
   - Anything framed as a real-world action still goes through a `station_ops_mitigation` DecisionRecord with policy engine, RBAC and approval.

## Consequences

- One process holds a few live twins in memory (~10–20 MB each). It is a local-first single-operator tool, not multi-tenant.
- Polling ~150 KB/s per open tab is fine locally. A WebSocket or delta protocol would be the step if this ever served many users.
- Agent quality is bounded by the twin's fidelity and by the proposed metric definitions and score weights; neither is validated against a real station.

## Revisit conditions

- Multi-user or remote use, which would need auth, per-user sessions and a push protocol.
- A real operational feed of any kind, which would need a new ADR before anything outside the twin could be touched.
