# CLAUDE.md

Instructions for AI coding assistants (Claude Code and others) working in this repository. Read [`HANDOFF.md`](HANDOFF.md) first for current state; this file is about *how* to work here, not *what* has been decided.

## What this project is

StationOS is a local-first logistics operations intelligence platform. Milestones 1–6 (software foundation; Cycle-1 domain model and event infrastructure; data engineering and analytics; digital twin; agentic AI system — one agent; reinforcement-learning environment — one decision problem) are complete; Milestone 7 (agent and RL coordination) is next. Full context: `docs/PRODUCT_VISION.md`, `docs/OPERATIONAL_DOMAIN_MODEL.md`, `docs/SYSTEM_ARCHITECTURE.md`, `docs/ENGINEERING_ROADMAP.md`, and `docs/adr/`.

## Hard rules

1. **Never introduce real operational data.** All parcel IDs, employee names, customer data, screenshots, or proprietary schemas are forbidden — synthetic data only. See `docs/SECURITY_AND_GOVERNANCE.md` §"Public repository safety". If asked to add real data, decline and explain why.
2. **Never invent proprietary metric formulas.** Metrics like DEA, OTD, FPY, FSAF are defined in `docs/OPERATIONAL_DOMAIN_MODEL.md` with status `requires_validation` where the exact calculation is unknown. Do not fill in a numerator/denominator you weren't given — propose it as a draft explicitly marked `proposed`, not `validated`.
3. **No autonomous control of physical operations, workforce, or dispatch.** StationOS is a decision-support system (see ADR-0009). Anything that would take an operationally consequential action must route through a human-approval gate, not execute directly.
4. **Don't jump ahead of the roadmap.** `docs/ENGINEERING_ROADMAP.md` defines ten sequenced milestones (foundation → domain/events → analytics → digital twin → agents → RL → agent/RL coordination → predictive intelligence → governance → frontend). If asked to build something from a later milestone, flag the dependency rather than silently scaffolding it out of order. Don't attempt more than one milestone per session.
5. **No premature infrastructure.** No Kafka until an actual streaming requirement justifies it (ADR-0004). No microservices split (ADR stack assumes a modular monolith) unless a new ADR revisits that. No mandatory cloud service (Snowflake, managed Postgres, etc.) for foundational workflows — see ADR-0001 and ADR-0010.
6. **LLM-provider independence.** Application code must go through the provider abstraction described in ADR-0008, not call a specific vendor SDK directly from agent/business logic.

## Conventions

- **Backend**: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, structlog. Linting via `ruff` (config in `backend/pyproject.toml`). Tests via `pytest` under `backend/tests/`.
- **Modular monolith**: one deployable backend, strict internal module boundaries (`domain`, `events`, `repositories`, `services`, `api`, `orchestration`, `agents`, `rl`, `simulation`, `analytics`, `security`) per `docs/SYSTEM_ARCHITECTURE.md`. A module only imports from layers below it in that architecture doc, never sideways into another vertical's internals.
- **Config**: all configuration via environment variables / `.env` through `app/core/config.py::Settings`. Never hardcode credentials or connection strings elsewhere.
- **Events**: every domain event needs `event_id`, `idempotency_key`, `correlation_id`, `schema_version`, `occurred_at`, `provenance`, and `source_kind`, per `docs/DATA_ARCHITECTURE.md`. There is one append-only `events` table (`app/events/models.py`), not one table per event type — don't add a second events table for a new event type, add a payload schema to `app/events/schemas.py::EVENT_PAYLOAD_SCHEMAS` instead.
- **Current state is a projection, never written directly.** A `Parcel`/`Truck` row's mutable fields (`lifecycle_state`, `classification`, `current_aisle_id`, `bag_id`, `status`, ...) are rebuilt by replaying that entity's event history (`app/services/event_ingestion.py`) — don't set them by hand anywhere else, even for a quick fix. If the projection logic is wrong, fix the projector, not the symptom at a call site.
- **An event with a missing or wrong predecessor is still persisted and still projected from** — flag `lifecycle_consistent = False` with a note, never silently drop a real event or pretend the sequence was fine.
- **Evidence labeling**: anything an agent emits must be tagged as one of `observation | calculated | inferred | hypothesis | prediction | recommendation` per `docs/AGENTIC_ARCHITECTURE.md`. Never present an inference or prediction as an observed fact.
- **ADRs**: a significant, hard-to-reverse architectural decision gets a new file in `docs/adr/` (format: `NNNN-title.md`, copy the structure of an existing one) before — not after — it's implemented. A roadmap-detail refinement or an implementation choice within an already-accepted ADR doesn't need a new one — update the existing doc/ADR with a dated note instead (see ADR-0007's amendment for the pattern).
- **Don't mock the database in tests that are supposed to verify persistence.** DB-dependent tests use the real `db_session` fixture (`tests/conftest.py`) and skip (via `pytest.skip`, not xfail) when Postgres isn't reachable — never substitute a mock for the thing actually being tested (constraint enforcement, idempotency, ordering).
- **Tests and local manual dev currently share one Postgres instance** — running `scripts/generate_synthetic_events.py --seed-db` and then `pytest` against the same database can leave Alembic's version table stale (tracked in `docs/OPEN_QUESTIONS.md`). If `alembic upgrade head` silently no-ops against a database that's missing its tables, that's why — drop `alembic_version` and re-run it, don't assume the migration is broken. In CI, this is why the seed/export/dbt steps run *before* pytest, not after.
- **The dbt project (`backend/analytics/`) is a separate tool, run separately.** Only `dbt-core`/`dbt-duckdb` are the `analytics` extra (not installed by default) — not invoked by the FastAPI app, no `subprocess` call to `dbt` from application code. `pandas`/`pyarrow`/`simpy`/`pyyaml` *are* base dependencies, unlike dbt — they back `app/events/parquet_io.py` and `app/simulation/`, which are core application modules, not a separately-run external tool.
- **A new event type needs its dbt test list updated too.** `backend/analytics/models/cleaned/_cleaned__models.yml`'s `accepted_values` test on `event_type` is a literal list that must mirror `backend/app/events/event_types.py` by hand (tracked in `docs/OPEN_QUESTIONS.md`) — add both together, not just the Python side.
- **A new dbt model needs a clear analytical purpose, not just plausibility.** `docs/ENGINEERING_ROADMAP.md`'s Milestone 3 non-goal is explicit: no dbt model should duplicate application logic (e.g. the event-ingestion projector) without a reason beyond "it could be useful."
- **Any code claiming reproducibility given a seed must get *every* "random" value — including UUIDs — from its own seeded `random.Random`, via `app/core/determinism.py::rng_uuid`/`rng_hex`.** Reaching for the system `uuid.uuid4()` or an unseeded `random` call anywhere in such code silently breaks determinism — this is not hypothetical, it shipped as a real bug in the Milestone 2 generator and had to be fixed.
- **The digital twin never touches PostgreSQL.** Simulated events (`app/simulation/model.py`) go straight to Parquet (`app/simulation/export.py`), tagged `source_kind = simulated` on every event — never through `EventStore`/`ingest_event`. See ADR-0006's amendment for why (a simulation run isn't "operational truth," ADR-0002). Don't add a path that ingests simulated data into Postgres without revisiting that decision deliberately, not as a side effect of unrelated work.
- **An agent is three plain functions (`gather_evidence`, `interpret`, `build_fallback_output`), not a base class to subclass.** See `app/orchestration/runner.py::AgentDefinition` and `app/agents/flow_intelligence/agent.py` for the pattern. This is what keeps an agent's own logic testable without any orchestration machinery involved (`tests/agents/flow_intelligence/test_agent.py`'s non-executor tests) — don't introduce an `Agent` base class agents inherit from instead.
- **`FakeLLMProvider` (`app/core/llm/fake.py`) is test-only, never a silent runtime default.** An agent with no real provider configured must fail loudly, not quietly return scripted output in production (`docs/AGENTIC_ARCHITECTURE.md` "Failure handling... never fabricate").
- **Restrict an LLM-facing output schema to only the evidence categories that step is actually allowed to produce — structurally, with `Literal[...]`, not by prompt instruction.** `app/agents/flow_intelligence/schemas.py::LLMFinding` only accepts `inferred`/`hypothesis`/`prediction` — Pydantic itself rejects `observation`/`calculated` (reserved for the deterministic path) and `recommendation` (no Layer 5 to approve one). Follow this pattern for every future agent's LLM-facing schema, don't rely on the prompt alone to hold the line.
- **`OllamaProvider` (`app/core/llm/ollama.py`) has not been verified against a real running Ollama server** — not installed on this development machine as of Milestone 5. Its request/response handling is verified against a mocked HTTP layer only (`tests/core/test_llm_ollama.py`). Don't claim or assume live-verified behavior beyond what those tests actually check; if you get a real Ollama server running, update `docs/OPEN_QUESTIONS.md` and ADR-0008's amendment once you do.
- **The `rl` extra (`gymnasium`, `stable-baselines3`, `torch`) is heavy and never a base dependency.** Install it explicitly (`pip install -e ".[dev,rl]"`) when working on `app/rl/` or running `scripts/train_rl_policy.py`/`scripts/run_rl_evaluation.py` — don't add it to the base `dependencies` list in `backend/pyproject.toml` the way `pandas`/`pyarrow`/`simpy` are, since most of the app never touches it.
- **A scenario YAML intended to show two policies behaving differently must be empirically verified to actually create contention before it's trusted.** Milestone 6 shipped a first RL scenario (generous hamper capacity, two stowers) where static and rule-based policies produced byte-identical trajectories — stow throughput was capacity-bound regardless of service order, so reordering never mattered. Don't assume a scenario config "should" create contention because the parameters look tight; run both baseline policies and diff their outcomes before building anything (training, evaluation, a held-out variant) on top of it. See `simulation/scenarios/rl_stow_balancing.yaml`'s tuning history in `docs/RL_ENVIRONMENT_SPEC.md`.
- **Never claim an RL policy is "better" because its training reward went up, or because reward beat a baseline's reward.** Report the actual metric-contract outcome (e.g. jackpot backlog, stow throughput) a reward was designed to serve, not the reward itself — a reward's own shaping terms can dominate the number without the thing it was meant to proxy actually improving. This is not hypothetical: Milestone 6's PPO policy had higher reward than both baselines in 2 of 3 evaluated scenarios, but its jackpot-backlog outcome — the metric that matters — was the same or worse than the baselines' in every scenario (`docs/RL_ENVIRONMENT_SPEC.md` §"Evaluation protocol and results", ADR-0007's amendment). Always run the full baseline comparison across multiple seeds and at least one held-out scenario before reporting any result, per ADR-0007.
- **A hard safety/anti-starvation constraint in an RL environment is enforced structurally in the environment, never left to the reward function to merely discourage.** `app/rl/env.py::AisleStowPriorityController` floors every per-aisle priority weight to `MIN_PRIORITY_WEIGHT` (never literal zero) so no aisle's stow priority can ever be fully starved by a policy's action, independent of whatever the reward happens to incentivize — per ADR-0009 and ADR-0007's "hard constraints... not reward penalties" stance.
- **`ml/` holds regenerable trained-model artifacts and is gitignored** (`ml/*`, keeping only `.gitkeep`) — a trained policy `.zip` or an evaluation report JSON is reproducible from `scripts/train_rl_policy.py`/`scripts/run_rl_evaluation.py` plus a documented seed, not something to commit. If a result needs to be preserved for the record, put the numbers in a doc (as `docs/RL_ENVIRONMENT_SPEC.md` does), not the binary artifact.

## Before implementing a new area of the system

1. Check whether an ADR already covers the decision; if it contradicts what you're about to do, stop and raise it rather than overriding silently.
2. Check `docs/OPEN_QUESTIONS.md` — if what you're about to build depends on an open question, implement the smallest version that doesn't require resolving it, or ask.
3. Keep the metric contract framework (`docs/OPERATIONAL_DOMAIN_MODEL.md` §2.4) in mind for anything metrics-adjacent — new metrics get a contract, not just a column.

## Commands

```bash
cd backend
pip install -e ".[dev]"
pytest              # run tests (DB-dependent ones skip honestly if Postgres isn't reachable)
ruff check .        # lint
alembic upgrade head   # apply migrations (needed once per fresh database)
uvicorn app.main:app --reload   # run the API locally
python scripts/generate_synthetic_events.py --seed 42 --seed-db   # seed reference data + a sample stream

# analytics pipeline (needs the `analytics` extra: pip install -e ".[dev,analytics]")
python scripts/export_events_to_parquet.py --out ../data/processed/events.parquet
cd analytics && dbt run --profiles-dir . && dbt test --profiles-dir .

# digital twin — no database needed
python scripts/run_simulation.py --scenario ../simulation/scenarios/normal_operations.yaml \
    --out ../data/processed/simulated_events.parquet

# Flow Intelligence Agent — see README.md "Running the Flow Intelligence Agent"
# for a full snippet; needs a DuckDB with analytics models built (above),
# and either a running Ollama server or FakeLLMProvider for the LLM step.

# RL environment (needs the `rl` extra: pip install -e ".[dev,rl]"); no database needed
python scripts/train_rl_policy.py --scenario ../simulation/scenarios/rl_stow_balancing.yaml \
    --timesteps 50000 --seed 1 --out ../ml/models/ppo_stow_balancing.zip
python scripts/run_rl_evaluation.py --policy ../ml/models/ppo_stow_balancing.zip \
    --out ../data/processed/rl_evaluation_report.json

# or, from the repo root, the full stack:
docker compose up -d
```

CI (`.github/workflows/ci.yml`) runs lint, `alembic upgrade head`, seed + export + `dbt run`/`dbt test`, then `pytest` — in that order (pytest last, because its own schema teardown would otherwise wipe the seeded data the dbt steps need) — against a real Postgres service container on every push/PR to `main`. Run the same sequence locally before pushing, don't rely on CI to catch it first. After any code change, actually run the tests and report what happened; don't report a change as done on the basis that it "should work."
