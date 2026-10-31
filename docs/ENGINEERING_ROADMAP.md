# Engineering Roadmap

Sequencing follows the dependency chain in `docs/PRODUCT_VISION.md` §"Capability arc": reliable data before intelligence, a calibrated twin before RL, agents before governed coordination. Each milestone lists a goal, deliverables, exit criteria, and explicit non-goals — a milestone is not "done" by vibes, and it does not sneak in work from a later milestone.

## Milestone 0 — Foundation (this phase, mostly complete)
**Goal**: architecture, documentation, and a minimal runnable skeleton.
**Delivered**: `docs/` (vision, domain model, architecture, data, agentic, digital twin, RL, security, roadmap, open questions), `docs/adr/`, `HANDOFF.md`, `CLAUDE.md`, `README.md`, `.gitignore`; backend skeleton (FastAPI app, settings, structured logging, Postgres + DuckDB connectors, `/health` + `/health/ready`, Alembic wiring, pytest suite).
**Exit criteria**: this document set is internally consistent; `pytest` passes in `backend/`; nothing is implemented beyond what's documented here.
**Non-goals**: any domain model, event, agent, simulation, or RL code.

## Milestone 1 — First commit and CI
**Goal**: get the existing work under version control with a minimal safety net.
**Deliverables**: initial commit of the foundation-phase tree; a GitHub Actions workflow running `ruff check` and `pytest` on push/PR; a `docker-compose.yml` bringing up PostgreSQL for local dev.
**Exit criteria**: CI is green on a clean clone; `docker compose up` + `pytest` passes with a real Postgres.
**Non-goals**: deployment pipeline beyond CI checks; any cloud environment.

## Milestone 2 — Domain model and event ingestion
**Goal**: Layer 1 + the writable half of Layer 2.
**Deliverables**: SQLAlchemy domain models for the entities in `docs/OPERATIONAL_DOMAIN_MODEL.md` §2 (first slice: truck, parcel, induct event, sort/hamper state — not the full entity list at once); Alembic migrations for them; an event schema (per `docs/DATA_ARCHITECTURE.md`) with idempotency/correlation/versioning fields; a repository layer; a synthetic event generator producing fixture data for `data/synthetic/`.
**Exit criteria**: a synthetic truck-arrival-through-stow event stream can be ingested, persisted, and read back via the repository layer, with duplicate/out-of-order events handled per spec.
**Non-goals**: analytics, agents, simulation, or UI.

## Milestone 3 — Analytical pipeline
**Goal**: the read half of Layer 2 + Layer 3's data foundation.
**Deliverables**: Parquet export of the Milestone 2 event log; dbt Core project modelling it into DuckDB; the `proposed`-status metrics from the metric contract catalog (WIPS, induct throughput, jackpot volume, dwell time, stow throughput) computed and queryable; data-quality checks per `docs/DATA_ARCHITECTURE.md` §"Data quality".
**Exit criteria**: a metric can be computed from synthetic data end-to-end and its contract marked with real (not placeholder) values for required source events and data-quality requirements.
**Non-goals**: the organization-specific metrics still marked `requires_validation` in `docs/OPERATIONAL_DOMAIN_MODEL.md` — they stay unimplemented until validated, not approximated.

## Milestone 4 — Digital twin baseline
**Goal**: a calibrated SimPy model of Cycle 1 (induct → sortation → stow).
**Deliverables**: scenario configuration format; the "normal volume" and "delayed inbound trucks" scenarios from `docs/DIGITAL_TWIN_SPEC.md`; simulation output in the same structural shape as Milestone 3's analytical tables, so simulated and real data are comparable.
**Exit criteria**: two scenarios run reproducibly (same seed → same output); output is queryable through the same analytical path as real data.
**Non-goals**: Cycle 2 (Pick & Stage/dispatch) simulation, RL, or the full ten-scenario catalog.

## Milestone 5 — Agent framework proof of concept
**Goal**: one agent, fully governed, end to end.
**Deliverables**: the orchestration state machine (ADR-0005); the model-provider abstraction (ADR-0008) with at least one real provider implementation; the Flow Intelligence Agent (narrowest-scoped agent, since Cycle 1 data exists from Milestone 2–4) with its full contract per `docs/AGENTIC_ARCHITECTURE.md`; evidence-category-tagged output.
**Exit criteria**: given a synthetic Cycle 1 scenario with an induced jackpot backlog, the agent produces a correctly-categorized finding (not a recommendation yet) citing real evidence from Milestones 2–4's data.
**Non-goals**: the full agent roster, multi-agent orchestration, or any recommendation requiring Layer 5 approval (Layer 5 doesn't exist yet).

## Milestone 6 — RL environment skeleton
**Goal**: answer "what is the first decision problem" and stand up a minimal environment for it.
**Deliverables**: resolution of the open question in `docs/RL_ENVIRONMENT_SPEC.md` (which narrow problem); a Gymnasium environment wrapping the Milestone 4 twin; a rule-based baseline policy; one trained PPO (or justified alternative) policy; an evaluation report comparing the two on held-out scenario variations.
**Exit criteria**: the evaluation report exists, is reproducible, and makes no claim beyond what the simulation actually showed.
**Non-goals**: applying the policy to anything beyond the twin; multi-agent RL; any claim of real-world performance.

## Milestone 7 — Governance layer and remaining agents
**Goal**: Layer 5 for real, plus the rest of the agent roster.
**Deliverables**: policy engine, constraint validation, risk evaluation, human-approval workflow, RBAC, audit records (`docs/SECURITY_AND_GOVERNANCE.md`); Station Orchestrator, Planning, Investigation, Dispatch Intelligence, Reconciliation and Returns agents.
**Exit criteria**: a recommendation from any agent cannot reach "acted on" status without passing through the full governance pipeline with an audit trail.
**Non-goals**: autonomous execution of any approved recommendation against a real system (there is no real system to act on yet).

## Milestone 8 — Operational experience
**Goal**: Layer 6, a usable command centre.
**Deliverables**: React/TypeScript frontend — dashboards for the metrics catalog, an investigation workspace surfacing agent findings with evidence categories visible, a simulation workspace for running digital-twin scenarios, a decision-history view backed by Milestone 7's audit records.
**Non-goals**: this is explicitly the last milestone in this roadmap — nothing here should get built early just because "it would be nice to see something."

## What's deliberately not sequenced yet

Cloud warehouse adapters (ADR-0010), Kafka-style streaming (ADR-0004), additional LLM providers beyond the first, and the full ten-scenario digital-twin catalog are all real future work but are not placed on the roadmap above because doing so now would be sequencing work ahead of the need that justifies it. They're tracked instead in `docs/OPEN_QUESTIONS.md` and the relevant ADR's "revisit conditions."
