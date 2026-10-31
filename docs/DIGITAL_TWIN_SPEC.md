# Digital Twin Specification

## Approach

A discrete-event simulation built with **SimPy**, living in `backend/app/simulation/` (the top-level `simulation/` directory holds scenario YAML files, not code — see §"Configuration" below). See ADR-0006 for why discrete-event simulation over alternatives (e.g., agent-based or continuous-time modelling), and its 2026-10-31 amendment for why simulated events are written straight to Parquet rather than through PostgreSQL.

## Modeled entities and resources

**Implemented (Milestone 4, Cycle 1 only)**:

| SimPy construct | Domain concept | Implementation |
|---|---|---|
| `Resource` | Induct belt/scanner capacity | `induct_station` — a shared resource every parcel queues for before its induct scan |
| `Resource` | Stower pool | `stower_pool` — a shared resource every parcel queues for before being stowed |
| Plain object (`_Hamper`, `level`/`capacity`) | Per-aisle hamper, finite capacity | Not a SimPy `Store`/`Container` — those block on a full `put()`, where the domain actually needs a non-blocking check-then-decide (full → jackpot immediately, not wait) |
| Replaceable `simpy.Event` (`_JackpotSignal`) | Periodic jackpot clearing, broadcast to everyone waiting at once | `_jackpot_clearing_process` fires on an interval, waking every parcel currently diverted, matching "jackpot must be cleared and reintroduced" as one supervisory action, not per-parcel retries |
| `Process` | A parcel's lifecycle (induct → classify → sort → [jackpot/clear loop] → stow), a truck's arrival/unload | `_parcel_process`, `_truck_process` |

Jackpot diversion **emerges from actual hamper capacity being full** when a sort is attempted — not a probability knob (unlike the Milestone 2 synthetic generator's `jackpot_rate`). This is the twin's real value-add over a naive random-timestamp generator: genuine resource contention.

**Not yet implemented**: Pick & Stage, dispatch waves, routes, vans, returns, planning (Cycle 2 — explicitly deferred, same Cycle-1-only scope as Milestone 2); the high-value/sideline/future-date/exception cage workflow (a non-`normal_cycle1` classification stops the simulated parcel at `pending_exception`, exactly mirroring the application-layer scope boundary — the twin doesn't invent a workflow the ingestion pipeline doesn't model either); scanners/induct belt as physically separate resources (combined into one `induct_station` resource for now); priority queueing (`PriorityResource`).

The full synthetic reference station (122 aisles, A1–A54/B1–B68) remains the config *default* (`app/simulation/config.py::StationLayoutConfig`), but the two shipped scenarios deliberately override it to a much smaller layout (10 aisles, hamper capacity 3) — see §"Configuration" for why.

## Configuration, not hardcoding

**Resolved** (`docs/OPEN_QUESTIONS.md`): **YAML, loaded into a typed Pydantic model** (`app/simulation.config.ScenarioConfig`), not a bare dict — a malformed scenario fails loudly at load time with a field-level error, not mid-simulation. Scenario files live in the top-level `simulation/scenarios/` directory. Every capacity/timing/resource count a scenario can vary is a config field; `app/simulation/model.py` never reads a literal count.

At the full 122-aisle reference scale, 125 parcels assigned uniformly at random would almost never fill a 40-capacity hamper — jackpot diversion would be theoretically possible but never actually exercised. The two shipped scenarios (`normal_operations.yaml`, `delayed_inbound_trucks.yaml`) use a 10-aisle, 3-capacity-hamper layout instead, specifically so contention shows up at a small, fast-to-simulate scale. This is a deliberate scenario-design choice, not a change to the reference defaults.

## Scenario catalog

| Scenario | What it varies | Status |
|---|---|---|
| Normal volume | Baseline inbound volume and resource levels | **Implemented** — `simulation/scenarios/normal_operations.yaml` |
| Delayed inbound trucks | Shifted truck arrival times, compressing downstream induct window | **Implemented** — `simulation/scenarios/delayed_inbound_trucks.yaml`; verified to actually produce a later, more compressed arrival window than `normal_operations` (not just a different seed) |
| Increased volume | Higher inbound parcel count, same resources | Not built — `ScenarioConfig.parcels.parcels_per_truck`/`truck_arrivals.truck_count` already support it; just needs a new YAML file |
| Reduced stower availability | Fewer stower resources than baseline | Not built — `resources.stower_count` already supports it |
| Unavailable aisles | One or more aisles removed from the sort cluster | Not built — would need a config field (e.g. an exclusion list) not yet added |
| Full hampers | Lower hamper capacity, forcing more jackpot diversion | Not built — `station_layout.hamper_capacity` already supports it; `normal_operations.yaml` already demonstrates this mechanism at a small scale |
| Jackpot accumulation | Jackpot clear rate reduced relative to divert rate | Not built — `resources.jackpot_clear_interval_minutes` already supports slowing clears |
| High-volume first wave, Late drivers, Route readiness constraints | Cycle 2 concepts (waves, drivers, routes) | Not built — blocked on Cycle 2 modelling, out of scope until Cycle 1 is validated per the roadmap |

Each implemented scenario produces a stream of the exact `EventEnvelope` objects the real ingestion pipeline uses (`app/events/schemas.py`), tagged `source_kind = simulated`, written to Parquet and readable by the unmodified `backend/analytics/` dbt project — verified directly: the same 9 models and 30 tests pass against simulated output as against real synthetic data, just pointed at a different Parquet file.

## Reproducibility

**Implemented and verified**: every simulation run returns a `SimulationResult` recording the scenario name, seed, SimPy version, a run ID, and a generation timestamp (`app/simulation/model.py`, written alongside the Parquet output as a `.manifest.json` by `app/simulation/export.py`). Re-running the same configuration + seed produces byte-for-byte identical event output, including every event's own `event_id` — verified by a test that runs a scenario twice and diffs the full serialized output. Every piece of randomness (entity UUIDs, event IDs, classification/aisle/resource choices) is drawn from one seeded `random.Random`, via shared helpers (`app/core/determinism.py`) that exist specifically because the Milestone 2 generator shipped a real non-determinism bug from reaching for the unseeded global `uuid.uuid4()` once already. The run ID itself is deliberately the one exception — generated from the unseeded system RNG, since it identifies *this execution* among possibly-many identical seeded replays, not part of the deterministic simulated content.

## Relationship to RL

The digital twin is the **environment** the RL layer trains and evaluates against (`docs/RL_ENVIRONMENT_SPEC.md`). It must exist and be reasonably calibrated before RL work starts — training a policy against an unvalidated simulation produces a policy tuned to the simulation's quirks, not the domain. This dependency is reflected in the roadmap sequencing (`docs/ENGINEERING_ROADMAP.md`): digital twin before RL environment.

## Explicitly out of scope for v1

- Real-time synchronization with live operational data (the twin runs scenarios, it does not yet mirror a live station state continuously).
- Visual/3D rendering of the station layout.
- Modeling individual named employees — stower/associate resources are anonymous, interchangeable capacity units, consistent with the synthetic-data requirement.
