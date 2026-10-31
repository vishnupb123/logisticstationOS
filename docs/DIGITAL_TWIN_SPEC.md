# Digital Twin Specification

## Approach

A discrete-event simulation built with **SimPy**, living in `backend/app/simulation/` (and the top-level `simulation/` directory for standalone scenario definitions/notebooks). See ADR-0006 for why discrete-event simulation over alternatives (e.g., agent-based or continuous-time modelling).

## Modeled entities and resources

Mapped directly from `docs/OPERATIONAL_DOMAIN_MODEL.md`:

| SimPy construct | Domain concept |
|---|---|
| `Resource` / `PriorityResource` | Induct belt, scanners, stower pool, high-value cage capacity |
| `Store` / `Container` | Hamper queues (per aisle, with finite capacity), jackpot accumulation, bag/cart contents |
| `Process` | A parcel's lifecycle (induct → classify → sort → stow → [Pick & Stage] → stage → dispatch), a truck's unload process, a wave's staging/dispatch process |
| Simulation clock | Drives the Cycle 1 → Cycle 2 → Planning sequence per `docs/OPERATIONAL_DOMAIN_MODEL.md` §3 |

Scope for the reference configuration: 122 aisles across two clusters (A1–A54, B1–B68), each with a hamper and scanner; a configurable stower pool; a single high-value exception workflow; a configurable cart/route/wave structure for Pick & Stage and dispatch. All counts are scenario parameters, not hardcoded constants — a scenario file can model a smaller or larger station.

## Configuration, not hardcoding

Every capacity, timing, and resource count is driven by a scenario configuration (YAML or JSON, exact format TBD at implementation time — tracked in `docs/OPEN_QUESTIONS.md`), not embedded in simulation code. This is what makes the scenario catalog below possible without forking the simulation.

## Scenario catalog (initial)

| Scenario | What it varies |
|---|---|
| Normal volume | Baseline inbound volume and resource levels |
| Increased volume | Higher inbound parcel count, same resources |
| Delayed inbound trucks | Shifted truck arrival times, compressing downstream induct window |
| Reduced stower availability | Fewer stower resources than baseline |
| Unavailable aisles | One or more aisles removed from the sort cluster |
| Full hampers | Lower hamper capacity, forcing more jackpot diversion |
| Jackpot accumulation | Jackpot clear rate reduced relative to divert rate |
| High-volume first wave | Disproportionate route/cart volume concentrated in Wave 1 |
| Late drivers | Delayed van departure independent of staging completeness |
| Route readiness constraints | Reduced picking/staging throughput ahead of a wave |

Each scenario produces a time series of station state (queue lengths, WIPS, jackpot volume, dwell times, wave readiness) that feeds the same analytical pipeline described in `docs/DATA_ARCHITECTURE.md` — simulated output and real operational data should be structurally comparable, not two incompatible formats.

## Reproducibility

Every simulation run records: the scenario configuration used, the random seed, the SimPy/library versions, and a run ID. Re-running the same configuration + seed must produce identical output — this is a hard requirement, not an aspiration, because both the RL environment (`docs/RL_ENVIRONMENT_SPEC.md`) and any "what would have happened" comparison depend on it.

## Relationship to RL

The digital twin is the **environment** the RL layer trains and evaluates against (`docs/RL_ENVIRONMENT_SPEC.md`). It must exist and be reasonably calibrated before RL work starts — training a policy against an unvalidated simulation produces a policy tuned to the simulation's quirks, not the domain. This dependency is reflected in the roadmap sequencing (`docs/ENGINEERING_ROADMAP.md`): digital twin before RL environment.

## Explicitly out of scope for v1

- Real-time synchronization with live operational data (the twin runs scenarios, it does not yet mirror a live station state continuously).
- Visual/3D rendering of the station layout.
- Modeling individual named employees — stower/associate resources are anonymous, interchangeable capacity units, consistent with the synthetic-data requirement.
