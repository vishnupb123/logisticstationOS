# ADR-0006: Digital-twin simulation approach

**Status**: Accepted

## Context

StationOS needs a digital twin of the station's process (induct, sortation, stow, Pick & Stage, dispatch) to support scenario evaluation and, later, to serve as the RL training/evaluation environment.

## Options considered

1. **Continuous-time / system-dynamics modelling** (e.g., differential equations over aggregate flow rates). Rejected: the domain is fundamentally made of discrete entities (parcels, trucks, carts) and discrete resource-contention events (hamper full, jackpot divert) that continuous aggregate models obscure rather than represent.
2. **Agent-based modelling with full behavioral agents for every associate/stower.** Rejected for v1: far more modelling and calibration effort than the current, well-defined decision problems need; the roadmap's scenario catalog doesn't require individually differentiated worker behavior.
3. **Discrete-event simulation (SimPy)**, modelling resources (scanners, hampers, stowers, cage capacity), entities (parcels, trucks, carts), and processes (lifecycle flows) directly. Chosen.

## Decision

The digital twin is a SimPy-based discrete-event model (`backend/app/simulation/`), with every capacity/timing/resource count driven by an external scenario configuration rather than hardcoded, per `docs/DIGITAL_TWIN_SPEC.md`.

## Rationale

Discrete-event simulation is the natural fit for queueing/capacity-constrained processes with identifiable entities and resources, which is exactly the structure in `docs/OPERATIONAL_DOMAIN_MODEL.md`. SimPy is a mature, well-understood Python library requiring no new infrastructure, consistent with the local-first principle (ADR-0001).

## Consequences

- Scenario definitions (`docs/DIGITAL_TWIN_SPEC.md` §"Scenario catalog") are data, not code — adding a scenario shouldn't require a code change to the simulation engine itself.
- Simulation output must be structured to match the real analytical data shape (`docs/DATA_ARCHITECTURE.md`), so simulated and real data are comparable through the same pipeline.
- Reproducibility (seeded runs, versioned config) is a hard requirement from the start, since the RL layer depends on it (ADR tie-in: `docs/RL_ENVIRONMENT_SPEC.md`).

## Risks

- Calibration without real operational data to validate against (by design — synthetic-data-only project) means "calibrated" can only mean internally consistent (e.g., conservation of parcels, sane queueing behavior), not validated against ground truth. This limitation must be stated explicitly wherever twin output is used, not glossed over.

## Revisit conditions

Revisit if a later use case needs individually differentiated worker behavior modelling (agent-based) or if performance at larger scale requires a different simulation engine — neither is a current need.
