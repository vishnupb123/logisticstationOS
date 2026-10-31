# StationOS — Engineering Handoff

**Purpose of this file**: the persistent, single source of truth for "where StationOS actually stands," written so a new engineering session (human or AI) can continue without this conversation's history. If something here conflicts with a doc in `docs/`, the more detailed doc wins for *content*; this file wins for *current status and what to do next*.

Last updated: 2026-10-31 (Milestone 3 completed this session).

---

## 1. Current milestone status

| Milestone | Status |
|---|---|
| 1 — Software foundation | ✅ Complete |
| 2 — Domain model and event infrastructure (Cycle 1 slice) | ✅ Complete |
| 3 — Data engineering and analytics | ✅ **Complete** (this session) |
| 4 — Digital twin | Not started — **next** |
| 5–10 | Not started |

Full milestone definitions: `docs/ENGINEERING_ROADMAP.md`.

## 2. What was built this session (Milestone 3)

**Parquet export** (`backend/app/services/parquet_export.py` + `backend/scripts/export_events_to_parquet.py`): exports only the `events` table from PostgreSQL — nothing from `app/domain` — to `data/processed/events.parquet`. Every Milestone 3 metric is derivable from the event log alone, so exporting the projected current-state tables too would be duplicating data for no analytical gain (and would blur the "Parquet is a derived artifact of the event log" principle from ADR-0003). `payload` (JSONB in Postgres) is serialized to a JSON *string* column, since Parquet has no native JSON type — DuckDB parses it back out with `->>`/`json_extract` in the dbt models.

**dbt Core project** (`backend/analytics/`, self-contained — `profiles.yml` lives in the project directory, not `~/.dbt/`, consistent with the local-first principle):
- `models/raw/raw_events.sql` — literal `read_parquet()` of the export.
- `models/cleaned/cleaned_events.sql` — typed envelope columns, `payload` cast to `JSON`.
- `models/curated/curated_parcel_events.sql` + `curated_parcel_lifecycle.sql` — payload fields flattened into typed columns; one row per parcel with its key Cycle-1 lifecycle timestamps. This deliberately **restates** (doesn't reuse) `app/services/event_ingestion.py`'s projection logic in SQL — the two serve different consumers (Postgres's current-state rows per write vs. a queryable analytical batch view) and the roadmap's own non-goal ("no dbt model should duplicate application logic without a clear analytical purpose") is about avoiding *pointless* duplication, not all duplication; this one has a purpose.
- `models/operational_intelligence/` — the five `proposed`-status metrics from `docs/OPERATIONAL_DOMAIN_MODEL.md` §4.1: `metric_wips`, `metric_induct_throughput`, `metric_jackpot_volume`, `metric_parcel_dwell_time`, `metric_stow_throughput`.
- 30 dbt tests total: `not_null`/`unique`/`accepted_values` generics across every layer, plus four singular tests — `assert_occurred_at_not_after_recorded_at.sql` (timestamp validity), `assert_no_missing_induct_event.sql` (referential integrity — the dbt-layer analogue of the projector's `lifecycle_consistent` flag, reinforced here because an analyst querying DuckDB directly can't see that flag), `assert_no_negative_dwell_time.sql` and `assert_jackpot_volume_non_negative.sql` (metric-contract requirements).

**No HTTP endpoint or `app/analytics` Python module was built** — same reasoning Milestone 2 applied to not exposing event ingestion over HTTP: there's no real consumer yet. A developer/analyst queries `data/analytics/stationos.duckdb` directly today.

**`pyproject.toml`**: added an `analytics` extra (`pandas`, `pyarrow`, `dbt-core<2.0`, `dbt-duckdb<2.0`) — not a base runtime dependency, since the API itself never invokes dbt or writes Parquet.

**CI** (`.github/workflows/ci.yml`): added seed → export → `dbt run` → `dbt test` steps, **before** the `pytest` step, not after — ordering is load-bearing here (see §4).

## 3. Verification performed (not claimed without running)

- Ran the exact CI sequence locally, in order, from a genuinely clean slate (fresh Postgres container + volume, fresh DuckDB file, fresh dbt `target/`): `ruff check` → `alembic upgrade head` → seed 6 trucks/20 parcels → export to Parquet → `dbt run` (9 models, all `OK`) → `dbt test` (30/30 `PASS`) → `pytest` (33/33 `passed`).
- Inspected the exported Parquet file's schema directly with DuckDB before building anything on top of it (confirmed JSON payload parsing works via `payload::JSON->>'outcome'`).
- Sanity-checked actual computed metric values, not just "the query ran": with 150 synthetic parcels (6 trucks × 25 parcels, a separate manual run) — 143 `normal_cycle1` parcels, all stowed; 2 `high_value`, 4 `exception`, 1 `future_date`, all correctly unstowed; jackpot cumulative diverts (10) exactly matched cumulative clears (10), `currently_in_jackpot = 0`; dwell times all positive, ranging 305–2348 seconds; `metric_wips = 0` for this closed batch (see §4 for why that's correct, not a bug).
- Fixed a real deprecation warning (`accepted_values` test arguments needing to be nested under an `arguments:` key in dbt 1.12) by actually reading dbt's output and fixing the schema files, not suppressing or ignoring the warning.

## 4. A finding worth understanding, not a bug: WIPS reads 0

`metric_wips` — "parcels inducted but not yet stowed" — reads `0` against the full synthetic-generator output. This is **correct**, not broken: the generator always carries every `normal_cycle1` parcel through to `stowed` by the time it finishes (there's no "the batch ended mid-process" scenario in a complete, closed synthetic run). WIPS is only ever non-zero against a dataset that captures a station *mid-operation* — a partial event stream, or a live/incremental export taken while parcels are still in flight. This is now documented explicitly in the metric's contract (`docs/OPERATIONAL_DOMAIN_MODEL.md` §4.1) and in the model's own SQL comment, specifically so a future session doesn't mistake `0` for a bug and "fix" it into something wrong.

## 5. Known limitations

- Parquet export is a full overwrite of one file, run manually/on-demand — no incrementality, no partitioning, no scheduler. Fine at this data volume; revisit if/when it isn't (tracked as a non-goal explicitly, not a forgotten gap).
- `backend/analytics/models/cleaned/_cleaned__models.yml`'s `accepted_values` test for `event_type` is a literal list that must be kept in sync by hand with `backend/app/events/event_types.py` — new open question, `docs/OPEN_QUESTIONS.md`.
- The tests-vs-dev-database isolation gap from Milestone 2 is unchanged; CI works around it by ordering (seed/export/dbt before pytest), which is a real, working mitigation but not the actual fix (a separate test database — still not built).
- No schema-conformance or freshness data-quality checks yet (see `docs/DATA_ARCHITECTURE.md` §"Data quality" for why: nothing to check `schema_version` conformance against with only one version per event type, and no live consumer yet for whom staleness would matter).

## 6. Open questions

Full register: `docs/OPEN_QUESTIONS.md`. New this session: the dbt/`event_types.py` manual-sync gap (above). Unchanged and still highest-priority: scenario/simulation-config file format (blocks Milestone 4), which LLM provider backs `LLMProvider` (blocks Milestone 5), metric formulas still `requires_validation` for the organization-specific metrics.

## 7. Security considerations

No change to governance stance. The `analytics` extra's new dependencies (`dbt-core`, `dbt-duckdb`, `pandas`, `pyarrow`) were checked against what they actually need — none require network access or credentials beyond the already-configured Postgres/DuckDB connections, and dbt's `profiles.yml` here contains no credentials (DuckDB is a local file, not a server with auth).

## 8. Recommended next milestone

**Milestone 4 — Digital twin** (`docs/ENGINEERING_ROADMAP.md`): a SimPy discrete-event model of Cycle 1 (induct → sortation → stow), starting with the "normal operations" and "delayed inbound trucks" scenarios, with reproducible (seeded) runs and output structured to match this milestone's analytical table shape so simulated and real data are comparable through the same pipeline. Digital-twin "calibration" can only mean internal consistency (conservation of parcels, sane queueing behavior) — there is no real operational data to validate against, by design.

## 9. Exact instructions for the next session

1. Read this file, then `docs/ENGINEERING_ROADMAP.md` Milestone 4, then `docs/DIGITAL_TWIN_SPEC.md` and ADR-0006.
2. Confirm Milestones 1–3 still work before building on them: `cd backend && pip install -e ".[dev,analytics]" && ruff check .`; then bring up Postgres (`docker compose up -d postgres`, remember the 5433 remap), `alembic upgrade head`, `python scripts/generate_synthetic_events.py --seed 42 --seed-db`, `python scripts/export_events_to_parquet.py --out ../data/processed/events.parquet`, `cd analytics && dbt run --profiles-dir . && dbt test --profiles-dir .`, then `cd .. && pytest -q` — in that order (seed/export/dbt before pytest, see §5).
3. The digital twin is new Python, likely under `backend/app/simulation/` (currently empty) plus a top-level `simulation/` directory for scenario definitions — check both existing empty dirs before deciding where code vs. config belongs.
4. Simulation output should be structured to match what the Milestone 3 analytics pipeline already consumes (the `events` table's shape, or something compatible with it) — so simulated and real data stay comparable through one pipeline, not two parallel ones. Worth deciding deliberately whether simulated events flow through the *same* `EventStore`/Parquet-export path (tagged `source_kind = simulated`) or a separate one; lean toward the same path given `source_kind` exists precisely to make that safe.
5. Resolve or make progress on the scenario-config file format open question (`docs/OPEN_QUESTIONS.md`) early — it blocks real implementation start.
6. When Milestone 4 is done: update this file's status table and date, run the full verification sequence from step 2 one more time and report the actual result, and update `docs/OPEN_QUESTIONS.md` for anything resolved or newly found.
