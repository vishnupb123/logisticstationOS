# StationOS — Product Vision

> **Synthetic domain notice**: StationOS models a fictional delivery station using synthetic data and generic parcel-logistics industry concepts. It is not built on, or validated against, any specific organization's confidential operational data, and does not claim integration with any real company's systems. See `docs/SECURITY_AND_GOVERNANCE.md`.

## What StationOS is

StationOS is an intelligent logistics operations platform that models a delivery station as a dynamic, capacity-constrained system, with the long-term goal of combining data engineering, operational analytics, event-driven architecture, digital-twin modelling, agentic AI, reinforcement learning, predictive modelling, decision governance, and human-in-the-loop operational intelligence into one coherent platform.

It is being built as a demonstration of **disciplined engineering**, not a demo app: typed interfaces, migrations, reproducible simulations, evidence-based AI output, and governed decision-making are first-class requirements from the start, even though most of the platform doesn't exist yet.

## Capability arc

StationOS is designed to grow through these capabilities, roughly in this order (see `docs/ENGINEERING_ROADMAP.md` for the concrete milestone sequence):

1. **Observe** — ingest structured operational events.
2. **Understand** — reconstruct current station state from those events.
3. **Investigate** — specialised agents gather evidence about operational problems.
4. **Predict** — forecast bottlenecks, delays, and operational risk.
5. **Simulate** — evaluate alternative operational decisions via a digital twin.
6. **Learn** — explore improved decision policies via reinforcement learning, for narrowly scoped, well-defined decision problems.
7. **Coordinate** — a governed multi-agent architecture assembles recommendations.
8. **Explain** — present evidence-backed recommendations, distinguishing fact from inference from prediction.
9. **Record** — log decisions, outcomes, and feedback for continuous evaluation.

Each capability is a precondition for the next. There is no path to useful RL or agentic coordination without reliable event data and state reconstruction first — this is why the roadmap front-loads data infrastructure.

## What StationOS is not

- **Not an autonomous operations controller.** It does not — and under current governance principles (ADR-0009), will not — directly control physical operations, parcel handling, dispatch, or workforce allocation. It is a decision-support system; a human approves anything operationally consequential.
- **Not a workforce-management tool.** VET/VTO and staffing are modeled only as configurable planning *concepts* for forecasting and simulation, never as autonomous actions on real people.
- **Not a wrapper around one AI vendor.** Claude Code / Claude CLI is a *development* tool used to build StationOS; production inference goes through a provider-independent abstraction (ADR-0008) so no component is hard-coded to a single vendor or a developer's personal subscription.
- **Not a demonstration of a specific company's internal systems.** All identifiers, volumes, and scenarios are synthetic.
- **Not cloud-dependent for its foundational workflows.** It must run on a developer's laptop with open-source tooling (ADR-0001).

## Evidence discipline

Every AI-generated operational finding must distinguish:

| Category | Meaning |
|---|---|
| Observation | A fact directly read from recorded events/state |
| Calculated result | A deterministic derivation from observations (a metric) |
| Inference | A conclusion drawn from incomplete or indirect evidence |
| Hypothesis | A proposed explanation not yet confirmed |
| Prediction | A forecast about future state, with stated uncertainty |
| Recommendation | A proposed action, with supporting evidence and alternatives considered |

An assumption must never be presented as an established operational fact. This rule is enforced structurally (typed evidence objects, not prose convention) once the agentic layer exists — see `docs/AGENTIC_ARCHITECTURE.md`.

## Current phase

This repository is in its **foundation phase**: architecture, domain model, and a minimal runnable backend skeleton exist; the application's business logic, digital twin, agents, and RL environment do not yet. See `HANDOFF.md` for exact current state and `docs/ENGINEERING_ROADMAP.md` for what's next.
