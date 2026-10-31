# StationOS

StationOS is an independent, enterprise-oriented **logistics operations intelligence platform**. It models a delivery station as a dynamic, capacity-constrained system and aims to grow into a decision-support platform that observes operational activity, investigates problems through specialised AI agents, predicts bottlenecks, simulates alternative decisions through a digital twin, and eventually learns improved decision policies through reinforcement learning — always with human-in-the-loop governance over anything operationally consequential.

See [`docs/PRODUCT_VISION.md`](docs/PRODUCT_VISION.md) for the full vision and [`HANDOFF.md`](HANDOFF.md) for the current engineering state and where to pick up next.

## ⚠️ Synthetic domain, public project

StationOS models a **fictional** delivery station ("Station NOVA-1") using **synthetic** data only. All parcel IDs, employee references, volumes, and operational examples in this repository are invented for engineering and research purposes.

This project is not affiliated with, endorsed by, or built on confidential data from any employer or company. It does not integrate with any real operator's systems. Operational terminology (induct, sortation, stow, dispatch, etc.) reflects generic parcel-logistics industry concepts, not a verified replica of any specific organization's proprietary process. See [`docs/SECURITY_AND_GOVERNANCE.md`](docs/SECURITY_AND_GOVERNANCE.md) §"Public repository safety" before contributing real-world data of any kind — don't.

## Current status: Milestone 1 complete (software foundation)

Milestone 1 — repository structure, local-first backend skeleton, Docker Compose, and CI — is done. **The product's actual domain model, events, analytics, simulation, agents, RL, and frontend are not implemented yet** — see [`docs/ENGINEERING_ROADMAP.md`](docs/ENGINEERING_ROADMAP.md) for what's next (Milestone 2: domain model and event infrastructure).

What runs today:
- A FastAPI backend (`backend/`) with structured logging, settings, liveness/readiness checks, and connectivity probes for PostgreSQL and DuckDB.
- `docker compose up` brings up PostgreSQL + the API together, verified end-to-end (`/health/ready` reports both dependencies `ok`).
- Alembic wired up for migrations (no domain models yet — `alembic/versions/` is empty).
- A pytest suite covering the health endpoints, and a GitHub Actions CI workflow (lint + test, against a real Postgres service container) running on every push/PR to `main`.

## Repository layout

```
backend/        FastAPI application (modular monolith) — see docs/SYSTEM_ARCHITECTURE.md
  app/
    api/        HTTP routes
    core/       settings, logging
    db/         PostgreSQL + DuckDB connection management
    domain/     domain entities (empty — Milestone 2)
    repositories/  data access (empty — Milestone 2)
    services/   application services (empty — Milestone 2+)
    orchestration/  agent orchestration / workflow state (empty — Milestone 5)
    agents/     specialised AI agents (empty — Milestone 5)
    rl/         reinforcement learning environment & training (empty — Milestone 6)
    simulation/ digital twin (empty — Milestone 4)
    analytics/  DuckDB/dbt-facing analytical services (empty — Milestone 3)
    security/   governance, RBAC, audit (empty — Milestones 7 & 9)
  tests/
  alembic/
data/           raw / processed / synthetic / analytics data (gitignored contents)
docs/           architecture, domain model, specs, ADRs — start here
frontend/       React/TypeScript command-centre UI (not started)
infra/          Docker / Docker Compose / CI definitions (not started)
ml/             RL training artifacts (not started)
simulation/     SimPy digital-twin scenarios (not started)
scripts/        developer/operational scripts (empty)
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

Brings up PostgreSQL and the API together. Host ports are intentionally remapped to **5433** (Postgres) and **8010** (API) rather than the defaults, because a developer machine commonly already has something on 5432/8000 — edit `docker-compose.yml` if that's not a concern for you. The API container mounts `./backend` (hot reload via `--reload`) and `./data` (so the embedded DuckDB file lands in the same place as a non-Docker run).

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

## License

Not yet decided — tracked in [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md).
