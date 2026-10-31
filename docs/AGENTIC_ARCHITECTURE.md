# Agentic Architecture

## Framework stance

Default to **a carefully designed custom state machine** (`backend/app/orchestration/`) over adopting LangGraph wholesale for v1 — see ADR-0005 for the evaluation and the revisit condition. Whatever is chosen, every agent needs: typed input/output schemas, explicit tool permissions, persistent execution state, checkpointing, retries/timeouts, evidence provenance, and a model-provider abstraction (ADR-0008). Agents never get unrestricted access to application data or arbitrary tools.

**Implemented (Milestone 5)**: `AgentExecutor`/`AgentDefinition` (`backend/app/orchestration/runner.py`). An agent is three plain functions — `gather_evidence`, `interpret`, `build_fallback_output` — not a framework base class to subclass; the executor wraps them with one checkpoint boundary (evidence persisted before the LLM step), bounded retries with a per-attempt timeout on `interpret` only (evidence-gathering is deterministic and isn't retried), and a `resume()` that continues a checkpointed execution without re-gathering evidence. Every execution is a row in `agent_executions` (PostgreSQL) — the audit record each agent contract's "Audit provenance" field points at.

## Hierarchical agent roster

### Station Orchestrator
Coordinates specialised agents, manages tasks, assembles findings, controls workflow state. The only agent allowed to invoke other agents; the only agent that writes to shared workflow state.

### Planning Agent
Investigates forecast volumes, truck arrivals, capacity, and planning scenarios. Reads from Layer 3 (analytics/simulation); never writes staffing decisions directly — produces a recommendation for human review (Layer 5).

### Investigation Agent
Investigates operational problems using evidence from relevant domain services. General-purpose evidence gatherer the Orchestrator dispatches for "what happened" questions.

### Flow Intelligence Agent — ✅ implemented (Milestone 5)
Analyses induct, sortation, stow, WIPS, jackpot, and capacity constraints (Cycle 1 domain).

Full contract (`backend/app/agents/flow_intelligence/agent.py`):

```
Agent: flow_intelligence
Responsibility: analyses induct, sortation, stow, WIPS, and jackpot metrics
    for Cycle 1, from the Milestone 3 analytics pipeline.
Input schema: FlowIntelligenceInput (duckdb_path)
Output schema: FlowIntelligenceOutput (findings: list[Finding], interpretation_error)
Tool permissions: query_jackpot_volume, query_wips, query_induct_throughput,
    query_stow_throughput, query_parcel_dwell_time — exactly these five
Persistent state: one agent_executions row per run (input, checkpointed
    evidence, output, status, timestamps)
Retry / timeout policy: up to 2 retries (3 attempts total) on the LLM
    interpretation step only, 30s timeout per attempt
Audit provenance: the agent_executions row itself
Evaluation criteria: deterministic findings' numbers exactly match the
    DuckDB source; every finding carries a valid EvidenceCategory; LLM
    findings restricted to inferred/hypothesis/prediction only
    (structurally, not by convention — see tests/agents/flow_intelligence/)
Failure handling: on exhausted LLM retries, returns the deterministic
    findings with interpretation_error set — never fabricates an LLM finding
```

Verified against a real induced jackpot backlog (synthetic generator → PostgreSQL → Parquet → dbt → agent, a mid-run snapshot truncated before all jackpot diverts had been cleared): the agent correctly reported an 18-parcel backlog (26 cumulative diverts, 8 cumulative clears) as an `observation`, citing `metric_jackpot_volume`, plus a correctly-tagged `hypothesis` from the LLM step. See `HANDOFF.md` for the full run.

### Dispatch Intelligence Agent
Analyses Pick & Stage, cart readiness, wave progress, route readiness, and departure risk (Cycle 2 domain).

### Reconciliation and Returns Agent
Investigates missing, duplicate, delayed, or inconsistent parcel lifecycle events, and returns processing.

## Per-agent contract

Every agent definition (Milestone 5) must specify:

```
Agent: <name>
Responsibility: <one sentence, non-overlapping with other agents>
Input schema: <typed, Pydantic>
Output schema: <typed, Pydantic — includes evidence category tags>
Tool permissions: <explicit allow-list, no wildcard>
Persistent state: <what's checkpointed, where>
Retry / timeout policy: <bounded, never infinite>
Audit provenance: <what gets logged per invocation>
Evaluation criteria: <how we'd know this agent is doing its job>
Failure handling: <degrade gracefully to "insufficient evidence", never fabricate>
```

No agent is implemented without this filled in; a stub agent with an empty contract is a roadmap item, not code.

## Evidence provenance

Every agent output is a typed object carrying one of the evidence categories from `docs/PRODUCT_VISION.md` §"Evidence discipline": `observation | calculated | inferred | hypothesis | prediction | recommendation`. This is enforced in the output schema itself — an agent cannot emit a bare string claim; it emits a structured finding with a category, supporting evidence references (which events/metrics it's based on), a time window, and, for predictions/recommendations, a confidence or uncertainty indicator and alternative explanations considered where relevant. The Orchestrator's job when assembling a final answer is to preserve these distinctions, not flatten them into undifferentiated prose.

## Tool permissions

Each agent is issued a specific, named set of tools (e.g., Flow Intelligence Agent might get `query_induct_metrics`, `query_jackpot_state`, `query_hamper_capacity` — not a generic "run SQL" tool). Tools are typed functions with validated inputs/outputs, not raw database or shell access. This is a governance boundary, not just an engineering convenience: it's what makes "agents must not have unrestricted access to application data" actually true rather than aspirational.

**Implemented**: the allow-list is enforced by what an agent module actually imports and calls (`backend/app/agents/flow_intelligence/tools.py`), not a runtime permission-checking registry — there is no dynamic, LLM-driven tool selection yet (the LLM never chooses which tool to call; `gather_evidence` always calls the same fixed five, deterministically, before the LLM is involved at all). A future agent whose evidence-gathering genuinely needs to vary by situation would need a real permission-checking layer; tracked as an open question, not built speculatively now.

## Model-provider abstraction

Agent code calls an internal `LLMProvider` interface (ADR-0008), never a vendor SDK directly. Claude Code/Claude CLI is the tool used to *build* StationOS during development; it is explicitly not assumed to be the production inference path, and no agent logic may depend on a developer's personal subscription being available at runtime.

**Implemented (Milestone 5)**: `backend/app/core/llm/` — `LLMProvider` (a `Protocol` with one method, `complete_structured`), `FakeLLMProvider` (scriptable, test-only), and `OllamaProvider` (the first real adapter, chosen by the project owner for true local-first operation — no API key, no cloud account). See ADR-0008's amendment for what "real" means here: the adapter's request/response handling is verified against a mocked HTTP layer; no live Ollama server was reachable on this development machine, so a genuine live call hasn't been exercised yet.

## Memory

Deferred in detail to Milestone 5, but the shape: agents get per-investigation working memory (scoped to one orchestration run, checkpointed) and the Orchestrator may persist decision/outcome records (Layer 5 audit) that a future investigation can query as evidence — this is explicitly *retrieval of past recorded decisions*, not an opaque long-term memory blob an agent writes to freely.

## What's explicitly out of scope for agents

- Taking any action with real-world effect (dispatch, workforce assignment, parcel routing) directly. Agents produce recommendations; Layer 5 governs whether/how a human acts on them.
- Treating an RL policy's output as agent-generated evidence without labeling it as what it is (a policy recommendation, evaluated in simulation) — see `docs/RL_ENVIRONMENT_SPEC.md` and `docs/SYSTEM_ARCHITECTURE.md` on keeping the two sub-layers interoperable but distinct.

**Milestone 7 update**: Layer 5 now exists (`backend/app/security/`), so the `recommendation` evidence category is meaningful for the first time — but it is produced by the new decision-coordination module (`app/security/decision_service.py`), not by any agent's own `interpret` step. The Flow Intelligence Agent is unchanged: its `LLMFinding` schema still structurally excludes `recommendation` (`app/agents/flow_intelligence/schemas.py`). A future agent whose own output should become a Layer-5-reviewable recommendation would need its output schema deliberately widened to allow it — that's a real design decision for a future milestone, not something this one did implicitly.

**Milestone 8 update**: `app/predictive/jackpot_risk/schemas.py::to_finding` is the first `prediction`-category finding sourced from a real trained statistical model rather than an LLM's free-text reasoning — its `confidence` field is the model's own predicted probability, a genuine uncertainty indicator, not a stand-in. Also not wired into any agent this milestone, for the same reason as Milestone 7's RL non-integration: see `docs/PREDICTIVE_INTELLIGENCE_SPEC.md` and `docs/OPEN_QUESTIONS.md`.
