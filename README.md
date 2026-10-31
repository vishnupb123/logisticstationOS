# StationOS

StationOS is an independent, enterprise-oriented **logistics operations intelligence platform**. It models a delivery station as a dynamic, capacity-constrained system and aims to grow into a decision-support platform that observes operational activity, investigates problems through specialised AI agents, predicts bottlenecks, simulates alternative decisions through a digital twin, and eventually learns improved decision policies through reinforcement learning — always with human-in-the-loop governance over anything operationally consequential.

See [`docs/PRODUCT_VISION.md`](docs/PRODUCT_VISION.md) for the full vision and [`HANDOFF.md`](HANDOFF.md) for the current engineering state and where to pick up next.

## ⚠️ Synthetic domain, public project

StationOS models a **fictional** delivery station ("Station NOVA-1") using **synthetic** data only. All parcel IDs, employee references, volumes, and operational examples in this repository are invented for engineering and research purposes.

This project is not affiliated with, endorsed by, or built on confidential data from any employer or company. It does not integrate with any real operator's systems. Operational terminology (induct, sortation, stow, dispatch, etc.) reflects generic parcel-logistics industry concepts, not a verified replica of any specific organization's proprietary process. See [`docs/SECURITY_AND_GOVERNANCE.md`](docs/SECURITY_AND_GOVERNANCE.md) §"Public repository safety" before contributing real-world data of any kind — don't.

## Current status: Milestones 1–7 complete (foundation + Cycle-1 domain/events + analytics + digital twin + first agent + RL environment + agent/RL decision governance)

**The frontend and the rest of the agent roster are not implemented yet** — see [`docs/ENGINEERING_ROADMAP.md`](docs/ENGINEERING_ROADMAP.md) for what's next (Milestone 8: predictive intelligence).

What runs today:
- A FastAPI backend (`backend/`) with structured logging, settings, liveness/readiness checks, and connectivity probes for PostgreSQL and DuckDB.
- `docker compose up` brings up PostgreSQL + the API together, verified end-to-end (`/health/ready` reports both dependencies `ok`).
- **Cycle 1 domain model and event infrastructure** (truck → induct → sort → stow only — Pick & Stage/dispatch and the high-value/exception cage workflows aren't modeled yet): typed, idempotent event ingestion into a single append-only `events` table, with current parcel/truck state rebuilt by replaying each entity's event history — order-independent and duplicate-safe by construction, not just by convention.
- A deterministic, seeded synthetic event generator and CLI: `python scripts/generate_synthetic_events.py --seed 42 --seed-db` (see [`HANDOFF.md`](HANDOFF.md) for exact usage and a known local-dev gotcha around running it against the same database as the test suite).
- **A dbt Core analytics pipeline** (`backend/analytics/`): Parquet export of the event log → layered dbt models (raw/cleaned/curated/operational_intelligence) against DuckDB → five computed, queryable metrics (WIPS, induct throughput, jackpot volume, parcel dwell time, stow throughput — `docs/OPERATIONAL_DOMAIN_MODEL.md` §4.1), backed by 30 dbt tests.
- **A SimPy digital twin** (`backend/app/simulation/`): a discrete-event model of Cycle 1 with real resource contention (shared induct/stower capacity, finite per-aisle hampers — jackpot diversion emerges from actual contention, not a probability knob), two scenarios, deterministic/seeded reproducibility, and output that runs through the *same* dbt project as real data (verified, not just asserted).
- **The Flow Intelligence Agent** (`backend/app/agents/flow_intelligence/`): the first real agent, orchestrated by a custom checkpoint/retry state machine (`backend/app/orchestration/`), backed by a provider-independent `LLMProvider` abstraction (`backend/app/core/llm/` — `OllamaProvider` for true local-first inference, no API key; `FakeLLMProvider` for tests). Produces evidence-category-tagged findings (`observation`/`calculated`/`inferred`/`hypothesis`/`prediction`) — never a bare string, never a `recommendation` (structurally impossible for this agent, not just discouraged). Verified against a real induced jackpot backlog running through the actual pipeline — see `HANDOFF.md`.
- **An RL environment** (`backend/app/rl/`): a Gymnasium environment wrapping the digital twin for one narrow decision problem (aisle-level stow priority balancing), with hard constraints enforced structurally, two baselines, and a PPO policy — evaluated across multiple seeds and held-out scenarios with an honest result: reward improved, but the metric that actually matters (jackpot backlog) didn't, and the advantage disappeared on the hardest held-out scenario. Full writeup in `docs/RL_ENVIRONMENT_SPEC.md`.
- **Agent/RL decision governance** (`backend/app/security/`): a policy engine, a (minimal, honestly-labeled) risk-evaluation stub, human approval, and a permanent audit record (`DecisionRecord`) connecting agent evidence and RL-environment-based candidate evaluation — never the trained PPO policy, deliberately, given its honest result above. The "no path lets a recommendation become acted on without approval" requirement is a structural guard in the repository functions, not a convention. See `docs/SECURITY_AND_GOVERNANCE.md` and ADR-0009.
- A 111-test pytest suite (pure logic + real-Postgres integration tests, the latter skipping honestly rather than failing when Postgres isn't reachable), and a GitHub Actions CI workflow (lint, migrate, seed + export + `dbt run`/`dbt test`, then pytest — against a real Postgres service container) on every push/PR to `main`.

## Repository layout

```
backend/        FastAPI application (modular monolith) — see docs/SYSTEM_ARCHITECTURE.md
  app/
    api/        HTTP routes
    core/       settings, logging, deterministic-RNG helpers, the LLMProvider abstraction (llm/)
    db/         PostgreSQL + DuckDB connection management
    domain/     domain entities — Station, Truck, Aisle, Hamper, Stower, Bag, Parcel (Cycle 1 only)
    events/     event envelope/payload schemas, the events table, EventStore, shared Parquet writer
    repositories/  typed lookups for trucks/parcels/aisles/stowers/bags
    services/   reference-data seeding, the event projector, the synthetic event generator, Parquet export
    simulation/ the digital twin — scenario config loading, the SimPy model, Parquet export
    orchestration/  AgentDefinition/AgentExecutor, the agent_executions audit table
    agents/     shared evidence types + the Flow Intelligence Agent
    analytics/  Python-side query interface onto the Milestone 3 DuckDB metrics
    rl/         StowBalancingEnv (Gymnasium) + static/rule-based/fixed-weight baselines + evaluation
    security/   policy engine, risk stub, decision records, approval/audit (Milestone 7; RBAC is Milestone 9)
  tests/
  alembic/      two migrations (Cycle-1 schema, agent_executions), upgrade/downgrade-verified
  scripts/      generate_synthetic_events.py, export_events_to_parquet.py, run_simulation.py
  analytics/    dbt Core project — raw/cleaned/curated/operational_intelligence models, 30 tests
data/           raw / processed / synthetic / analytics data (gitignored contents)
docs/           architecture, domain model, specs, ADRs — start here
frontend/       React/TypeScript command-centre UI (not started)
infra/          Docker / Docker Compose / CI definitions (not started)
ml/             trained RL policies (gitignored — regenerate via backend/scripts/train_rl_policy.py)
simulation/     digital-twin scenario YAML files — normal_operations.yaml, delayed_inbound_trucks.yaml
scripts/        repo-level developer/operational scripts (empty — distinct from backend/scripts/)
```

## Documentation map

| Document | Purpose |
|---|---|
| [`HANDOFF.md`](HANDOFF.md) | Persistent engineering handoff — state, decisions, open questions, next steps |
| [`CLAUDE.md`](CLAUDE.md) | Project-specific instructions for AI coding assistants working in this repo |
| [`docs/PRODUCT_VISION.md`](docs/PRODUCT_VISION.md) | What StationOS is, and isn't |
| [`docs/OPERATIONAL_DOMAIN_MODEL.md`](docs/OPERATIONAL_DOMAIN_MODEL.md) | The synthetic station process being modeled |
| [`docs/SYSTEM_ARCHITECTURE.md`](docs/SYSTEM_ARCHITECTURE.md) | Six-layer architecture, modular monolith |
| [`docs/DATA_ARCHITECTURE.md`](docs/DATA_ARCHITECTURE.md) | PostgreSQL / DuckDB / Parquet / dbt responsibilities |
| [`docs/AGENTIC_ARCHITECTURE.md`](docs/AGENTIC_ARCHITECTURE.md) | Hierarchical agent design |
| [`docs/DIGITAL_TWIN_SPEC.md`](docs/DIGITAL_TWIN_SPEC.md) | SimPy discrete-event station model |
| [`docs/RL_ENVIRONMENT_SPEC.md`](docs/RL_ENVIRONMENT_SPEC.md) | Reinforcement-learning research scope |
| [`docs/SECURITY_AND_GOVERNANCE.md`](docs/SECURITY_AND_GOVERNANCE.md) | Human-in-the-loop governance, secrets, public-repo safety |
| [`docs/ENGINEERING_ROADMAP.md`](docs/ENGINEERING_ROADMAP.md) | Milestones and sequencing |
| [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) | Tracked unknowns requiring validation or a decision |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records |

## Local development

### Option A — Docker Compose (full stack)

```bash
docker compose up -d
curl http://localhost:8010/health/ready
```

Brings up PostgreSQL and the API together. Host ports are intentionally remapped to **5433** (Postgres) and **8010** (API) rather than the defaults, because a developer machine commonly already has something on 5432/8000 — edit `docker-compose.yml` if that's not a concern for you. The API container mounts `./backend` (hot reload via `--reload`) and `./data` (so the embedded DuckDB file lands in the same place as a non-Docker run). The container does not run migrations automatically — apply them once per fresh database (see below).

### Option B — Python venv (API only, no Postgres)

Requires Python 3.11+.

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn app.main:app --reload
```

`GET /health` and `GET /health/ready` are available once the server is running (default `http://localhost:8000`). PostgreSQL connection settings are read from environment variables (see `app/core/config.py` / `backend/.env.example`); without a running PostgreSQL instance, `/health/ready` reports `postgres: unreachable` rather than failing — that's expected, not a bug, if you're running this option without also starting Postgres separately.

### Applying migrations and generating synthetic data

Once Postgres is up (either option), from `backend/` with the venv active (set `POSTGRES_PORT=5433` if you're pointing at the Docker Compose Postgres rather than a locally-installed one):

```bash
alembic upgrade head                                    # creates the Cycle-1 schema
python scripts/generate_synthetic_events.py --seed 42 --seed-db   # seeds reference data + a sample event stream
```

⚠️ Don't run `pytest` against the same database right after seeding dev data this way — the test suite creates and drops its own copy of every table directly (bypassing Alembic), which leaves Alembic's own version-tracking table out of sync with reality. If `alembic upgrade head` then silently does nothing against a database missing its tables, drop `alembic_version` and re-run it. Tracked as a real gap in [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) — the proper fix is a separate test database, not yet built.

### Running the analytics pipeline

Requires the `analytics` extra (`pip install -e ".[dev,analytics]"`) and some seeded data (see above). From `backend/`:

```bash
python scripts/export_events_to_parquet.py --out ../data/processed/events.parquet
cd analytics
dbt run --profiles-dir .
dbt test --profiles-dir .
```

Then query `data/analytics/stationos.duckdb` directly (`duckdb data/analytics/stationos.duckdb` or via Python's `duckdb` package) — there's no API endpoint for these metrics yet; see `docs/DATA_ARCHITECTURE.md` for why.

### Running the digital twin

No database needed — the twin never touches PostgreSQL (see ADR-0006's amendment for why). From `backend/`:

```bash
python scripts/run_simulation.py --scenario ../simulation/scenarios/normal_operations.yaml \
    --out ../data/processed/simulated_events.parquet
```

Writes the Parquet file plus a `.manifest.json` (scenario, seed, SimPy version, run id). To run it through the same analytics pipeline as real data, point dbt at it instead of the real export:

```bash
cd analytics
STATIONOS_EVENTS_PARQUET=../../data/processed/simulated_events.parquet \
STATIONOS_DUCKDB_PATH=/tmp/stationos_sim.duckdb \
dbt run --profiles-dir . && dbt test --profiles-dir .
```

### Running the Flow Intelligence Agent

Needs a DuckDB file with the analytics models already built (see "Running the analytics pipeline" above). No database write required for this quick check — only `app/orchestration`'s persistence does. With the venv active, from `backend/`:

```python
from app.agents.flow_intelligence.agent import AGENT
from app.agents.flow_intelligence.schemas import FlowIntelligenceInput
from app.core.llm.ollama import OllamaProvider  # or FakeLLMProvider — see below
from app.db.postgres import SessionLocal
from app.orchestration.runner import AgentExecutor

llm = OllamaProvider(base_url="http://localhost:11434", model="llama3.1")  # requires Ollama running
session = SessionLocal()
output = AgentExecutor(session, llm).run(AGENT, FlowIntelligenceInput(duckdb_path="../data/analytics/stationos.duckdb"))
session.commit()
for finding in output.findings:
    print(finding.category, finding.summary)
```

⚠️ `OllamaProvider` needs a real Ollama server (`ollama serve`, with `ollama pull llama3.1` or whatever `Settings.ollama_model` names) — not installed by default, not verified against a live server this session (`docs/OPEN_QUESTIONS.md`). Swap in `app.core.llm.fake.FakeLLMProvider([...])` with a scripted response to run the agent without Ollama — see `backend/tests/agents/flow_intelligence/test_agent.py` for worked examples, including the exact induced-jackpot-backlog scenario the agent is evaluated against.

### Running the RL environment

Needs the `rl` extra (`pip install -e ".[dev,rl]"`) — heavy (torch), not installed by default. No database needed. From `backend/`:

```bash
python scripts/train_rl_policy.py --scenario ../simulation/scenarios/rl_stow_balancing.yaml \
    --timesteps 50000 --out ../ml/models/ppo_stow_balancing.zip
python scripts/run_rl_evaluation.py --policy ../ml/models/ppo_stow_balancing.zip \
    --out ../data/processed/rl_evaluation_report.json
```

The second command prints a results table and reruns reproducibly (verified: re-running against the same policy file produces a byte-identical report). See `docs/RL_ENVIRONMENT_SPEC.md` for what the numbers actually showed — a reward improvement that didn't translate into a backlog improvement, reported honestly rather than oversold.

### Running the agent/RL decision governance pipeline

Needs the `rl` extra and a running Postgres with migrations applied (`alembic upgrade head`). From `backend/`:

```bash
python scripts/run_decision_demo.py
```

Proposes a decision (evaluating named candidate priority-interventions via real simulation runs), runs it through the policy engine, attempts — and is refused — to record an outcome before approval, has a human approve a candidate, then runs a fresh simulation to record the observed outcome. Verified reproducible across repeated runs. See `docs/SECURITY_AND_GOVERNANCE.md` and ADR-0009 for the governance pipeline this demonstrates.

## License

Not yet decided — tracked in [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md).
