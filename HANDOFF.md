# StationOS — Engineering Handoff

**Purpose of this file**: the persistent, single source of truth for "where StationOS actually stands," written so a new engineering session (human or AI) can continue without this conversation's history. If something here conflicts with a doc in `docs/`, the more detailed doc wins for *content*; this file wins for *current status and what to do next*.

Last updated: 2026-10-31 (Milestone 4 completed this session).

---

## 1. Current milestone status

| Milestone | Status |
|---|---|
| 1 — Software foundation | ✅ Complete |
| 2 — Domain model and event infrastructure (Cycle 1 slice) | ✅ Complete |
| 3 — Data engineering and analytics | ✅ Complete |
| 4 — Digital twin | ✅ **Complete** (this session) |
| 5 — Agentic AI system | Not started — **next** |
| 6–10 | Not started |

Full milestone definitions: `docs/ENGINEERING_ROADMAP.md`.

## 2. What was built this session (Milestone 4)

**Scenario configuration** (`backend/app/simulation/config.py`): YAML loaded into a typed Pydantic `ScenarioConfig` (station layout, truck arrivals, parcel timing/rates, resource levels) — resolves the scenario-config-format open question from the architecture phase. A malformed scenario file fails loudly at load time, not mid-simulation.

**The SimPy model** (`backend/app/simulation/model.py`) — the qualitative improvement over Milestone 2's generator: **real resource contention**, not random timestamps. A shared `induct_station` resource, a shared `stower_pool` resource, and per-aisle hampers (plain objects with `level`/`capacity`, not SimPy's `Container` — that blocks on a full `put()`, where the domain needs a non-blocking check-then-decide). Jackpot diversion **emerges from hampers actually being full** when a sort is attempted, not a probability knob. A periodically-replaced `simpy.Event` (`_JackpotSignal`) broadcasts jackpot clearing to every waiting parcel at once, matching "jackpot must be cleared and reintroduced" as one supervisory action rather than per-parcel retries.

**Two required scenarios** (`simulation/scenarios/`): `normal_operations.yaml`, `delayed_inbound_trucks.yaml`. Both deliberately use a 10-aisle, 3-capacity-hamper layout (not the full 122-aisle reference default) — at reference scale, 125 parcels spread uniformly would almost never fill a 40-capacity hamper, so the contention mechanism would be theoretically present but never actually exercised. Verified the two scenarios are meaningfully distinct (later, more compressed truck arrivals), not copies with a different seed.

**Shared determinism helpers** (`backend/app/core/determinism.py`): `rng_uuid`/`rng_hex`, extracted from the Milestone 2 generator (which previously had its own private copies) specifically because getting this wrong once already shipped a real bug (see §4). Both the generator and the twin now import from one place.

**Output path** (`backend/app/simulation/export.py` + `backend/app/events/parquet_io.py`, the latter also extracted from `app/services/parquet_export.py` so both Milestone 3's PostgreSQL export and Milestone 4's simulation output share one Parquet-writing implementation): simulated events are the exact same `EventEnvelope` objects the real pipeline uses, tagged `source_kind = SIMULATED` on every event, written **straight to Parquet — never through PostgreSQL/EventStore**. This is a real architectural decision, not a default fallen into — recorded as a dated amendment to ADR-0006. Rationale: a simulation run isn't "operational truth" (ADR-0002); comparability with real data is achieved at the schema/dbt level, not by mixing simulated rows into the operational database.

**CLI**: `backend/scripts/run_simulation.py` — runs a scenario, writes Parquet + a `.manifest.json` (scenario, seed, SimPy version, run id, generated-at — docs/DIGITAL_TWIN_SPEC.md's reproducibility requirements).

**Dependency changes**: `simpy`, `pyyaml`, `pandas`, `pyarrow` promoted to base dependencies in `backend/pyproject.toml` (previously `pandas`/`pyarrow` were in the `analytics` extra) — `app/simulation` and `app/events/parquet_io.py` are core application modules, not a side tool, unlike dbt (which stays in the `analytics` extra, genuinely a separate CLI tool).

**16 new tests** (`backend/tests/simulation/`): config loading/validation, determinism (same seed → byte-identical output including `event_id`), conservation (every simulated parcel ends in a terminal state, verified via the *real* `event_ingestion.project_parcel` function — not a twin-specific reimplementation of the check), forced jackpot contention, the two shipped scenarios actually differing, Parquet round-trip, run-manifest content.

## 3. A real design mistake caught and fixed before it shipped

While writing `model.py`, I initially copied Milestone 2's per-event-type `source_kind` pattern (`PHYSICAL_OBSERVATION` for scan-like events, `SYSTEM_RECORDED` for bookkeeping events) directly into the twin. That's wrong for a simulation: **every** event the twin produces is simulated — none of them represent a real physical observation or a real system's bookkeeping. Caught this by re-reading the module's own docstring (which already correctly said "tagged `source_kind=SIMULATED`") against the code I'd actually written, which didn't match it. Fixed by removing `source_kind` as a per-call parameter entirely and hardcoding `EventSourceKind.SIMULATED` inside `_Context.emit()` — structurally impossible to get wrong at a call site now, not just corrected this once. Verified via `test_export.py::test_parquet_round_trips...` asserting `frame["source_kind"].eq("simulated").all()`, and by direct DuckDB inspection after running the actual dbt pipeline against simulated output (`SELECT DISTINCT source_kind FROM cleaned_events` → exactly `simulated`, nothing else).

## 4. Verification performed (not claimed without running)

- Ran `ruff check .` clean across all new/modified code.
- Ran the full 49-test backend suite (33 from Milestones 2–3 + 16 new) against a live Postgres — all passed; confirmed the determinism refactor (`app/core/determinism.py`) didn't change the Milestone 2 generator's behavior (its own 5 tests still pass unchanged).
- Ran both shipped scenarios directly (not just via pytest): inspected actual event counts and type breakdowns, confirmed internal consistency by hand (e.g., `sort_attempted(sorted) count == stowed count`; `jackpot occurrences == jackpot_cleared count`), confirmed every event validates against the real production Pydantic schemas (`app.events.schemas.validate_payload`), confirmed zero inconsistent/non-terminal parcels via the real projector.
- **The headline verification**: ran the *unmodified* `backend/analytics/` dbt project (same `dbt_project.yml`, same models, same tests) against simulated Parquet output instead of real synthetic-generator output, by pointing `STATIONOS_EVENTS_PARQUET`/`STATIONOS_DUCKDB_PATH` at different files — got the same 9 models built and all 30 tests passing. This is the literal, verified truth of the roadmap's exit criteria ("simulated and real data are comparable through the same pipeline"), not an assertion resting on the two formats merely looking similar on paper.
- Checked computed metrics against simulated data for sanity: `metric_wips = 0` (consistent with Milestone 3's documented finding — a closed run always reads 0), jackpot diverts exactly matched clears, dwell times short but positive (the twin's timing config is deliberately fast for test purposes, not meant to replicate real durations).

## 5. Known limitations

- Cycle 2 (Pick & Stage, dispatch waves, routes, vans, returns) is not simulated — same Cycle-1-only scope as Milestone 2, by design.
- The high-value/sideline/future-date/exception cage workflow is not simulated — a non-`normal_cycle1` classification stops the simulated parcel at `pending_exception`, mirroring the (also-unmodeled) application-layer boundary.
- Only 2 of the 10 catalogued scenarios are built (`docs/DIGITAL_TWIN_SPEC.md` §"Scenario catalog" now states which config fields already support each of the other 8 without new code, and which would need a new config field).
- Induct scanning and classification are combined into one resource/decision point rather than physically separate stations — a deliberate simplification, not an oversight.
- `app/simulation` has no priority queueing (`simpy.PriorityResource`) — not needed by either shipped scenario.
- The tests-vs-dev-database isolation gap from Milestone 2 is unchanged and doesn't affect this milestone (the twin never touches Postgres at all).

## 6. Open questions

Full register: `docs/OPEN_QUESTIONS.md`. Resolved this session: scenario-config-format (YAML + Pydantic). Updated: the station-profile question now notes `ScenarioConfig.station_layout` as the de facto answer, with a reusable "profile" abstraction still not built since nothing needs a second layout yet. Unchanged and highest-priority for what's ahead: which LLM provider backs `LLMProvider` (blocks Milestone 5), metric formulas still `requires_validation` for the organization-specific metrics, the dbt/`event_types.py` manual-sync gap.

## 7. Security considerations

No change to governance stance. The twin produces no real data and never touches PostgreSQL, so there's no new surface for real/simulated data to be confused in the operational store — that's structural (ADR-0006's amendment), not a discipline to maintain by convention.

## 8. Recommended next milestone

**Milestone 5 — Agentic AI system** (`docs/ENGINEERING_ROADMAP.md`): the orchestration state machine (ADR-0005), the `LLMProvider` abstraction (ADR-0008) with at least one real provider adapter, and the Flow Intelligence Agent (narrowest-scoped, since Cycle 1 data exists from Milestones 2–4) with its full contract — typed input/output, explicit tool permissions, persistent state, checkpointing, retry/timeout, execution tracing, evaluation tests — producing evidence-category-tagged output (`observation | calculated | inferred | hypothesis | prediction | recommendation`).

## 9. Exact instructions for the next session

1. Read this file, then `docs/ENGINEERING_ROADMAP.md` Milestone 5, then `docs/AGENTIC_ARCHITECTURE.md` and ADR-0005/ADR-0008.
2. Confirm Milestones 1–4 still work: `cd backend && pip install -e ".[dev,analytics]" && ruff check .`; bring up Postgres, `alembic upgrade head`, run `pytest -q` (49 tests, DB-dependent ones skip if Postgres isn't up); run both scenarios via `scripts/run_simulation.py` and confirm they still produce sane output.
3. Milestone 5's first concrete decision is which LLM provider implements `LLMProvider` for real (`docs/OPEN_QUESTIONS.md`) — this blocks everything else in the milestone and should be resolved or explicitly raised early, not discovered mid-implementation.
4. The Flow Intelligence Agent's evidence should be able to cite the Milestone 3 analytics pipeline's metrics and/or the Milestone 4 twin's scenario comparisons — check both are queryable (via DuckDB directly, since there's still no API layer onto either) before assuming what evidence is actually available to ground the agent's output in.
5. Respect the evidence-category scheme from the start (`docs/AGENTIC_ARCHITECTURE.md`) — this is a structural requirement (typed output, not prose convention), not something to retrofit after a first working version.
6. When Milestone 5 is done: update this file's status table and date, run the full verification sequence from step 2 one more time and report the actual result, and update `docs/OPEN_QUESTIONS.md` for anything resolved or newly found.
