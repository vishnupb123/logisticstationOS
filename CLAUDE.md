# CLAUDE.md

Instructions for AI coding assistants (Claude Code and others) working in this repository. Read [`HANDOFF.md`](HANDOFF.md) first for current state; this file is about *how* to work here, not *what* has been decided.

## What this project is

StationOS is a local-first logistics operations intelligence platform in its foundation phase. Full context: `docs/PRODUCT_VISION.md`, `docs/OPERATIONAL_DOMAIN_MODEL.md`, `docs/SYSTEM_ARCHITECTURE.md`, and `docs/adr/`.

## Hard rules

1. **Never introduce real operational data.** All parcel IDs, employee names, customer data, screenshots, or proprietary schemas are forbidden — synthetic data only. See `docs/SECURITY_AND_GOVERNANCE.md` §"Public repository safety". If asked to add real data, decline and explain why.
2. **Never invent proprietary metric formulas.** Metrics like DEA, OTD, FPY, FSAF are defined in `docs/OPERATIONAL_DOMAIN_MODEL.md` with status `requires_validation` where the exact calculation is unknown. Do not fill in a numerator/denominator you weren't given — propose it as a draft explicitly marked `proposed`, not `validated`.
3. **No autonomous control of physical operations, workforce, or dispatch.** StationOS is a decision-support system (see ADR-0009). Anything that would take an operationally consequential action must route through a human-approval gate, not execute directly.
4. **Don't jump ahead of the roadmap.** `docs/ENGINEERING_ROADMAP.md` defines milestone sequencing (domain models → events → analytics → digital twin → agents → RL → frontend → governance). If asked to build something from a later milestone, flag the dependency rather than silently scaffolding it out of order.
5. **No premature infrastructure.** No Kafka until an actual streaming requirement justifies it (ADR-0004). No microservices split (ADR stack assumes a modular monolith) unless a new ADR revisits that. No mandatory cloud service (Snowflake, managed Postgres, etc.) for foundational workflows — see ADR-0001 and ADR-0010.
6. **LLM-provider independence.** Application code must go through the provider abstraction described in ADR-0008, not call a specific vendor SDK directly from agent/business logic.

## Conventions

- **Backend**: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, structlog. Linting via `ruff` (config in `backend/pyproject.toml`). Tests via `pytest` under `backend/tests/`.
- **Modular monolith**: one deployable backend, strict internal module boundaries (`domain`, `repositories`, `services`, `api`, `orchestration`, `agents`, `rl`, `simulation`, `analytics`, `security`) per `docs/SYSTEM_ARCHITECTURE.md`. A module only imports from layers below it in that architecture doc, never sideways into another vertical's internals.
- **Config**: all configuration via environment variables / `.env` through `app/core/config.py::Settings`. Never hardcode credentials or connection strings elsewhere.
- **Events** (once introduced): every domain event needs `event_id`, `idempotency_key`, `correlation_id`, `schema_version`, `occurred_at`, and a provenance field, per `docs/DATA_ARCHITECTURE.md`.
- **Evidence labeling**: anything an agent emits must be tagged as one of `observation | calculated | inferred | hypothesis | prediction | recommendation` per `docs/AGENTIC_ARCHITECTURE.md`. Never present an inference or prediction as an observed fact.
- **ADRs**: a significant, hard-to-reverse architectural decision gets a new file in `docs/adr/` (format: `NNNN-title.md`, copy the structure of an existing one) before — not after — it's implemented.

## Before implementing a new area of the system

1. Check whether an ADR already covers the decision; if it contradicts what you're about to do, stop and raise it rather than overriding silently.
2. Check `docs/OPEN_QUESTIONS.md` — if what you're about to build depends on an open question, implement the smallest version that doesn't require resolving it, or ask.
3. Keep the metric contract framework (`docs/OPERATIONAL_DOMAIN_MODEL.md` §2.4) in mind for anything metrics-adjacent — new metrics get a contract, not just a column.

## Commands

```bash
cd backend
pip install -e ".[dev]"
pytest              # run tests
ruff check .        # lint
uvicorn app.main:app --reload   # run the API locally
```

There is no CI workflow yet (`.github/workflows/` is empty) and no `docker-compose.yml` yet — both are Milestone 2 items, tracked in `docs/ENGINEERING_ROADMAP.md`.
