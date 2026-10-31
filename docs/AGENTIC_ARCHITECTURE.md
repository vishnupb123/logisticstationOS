# Agentic Architecture

## Framework stance

Default to **a carefully designed custom state machine** (`backend/app/orchestration/`) over adopting LangGraph wholesale for v1 — see ADR-0005 for the evaluation and the revisit condition. Whatever is chosen, every agent needs: typed input/output schemas, explicit tool permissions, persistent execution state, checkpointing, retries/timeouts, evidence provenance, and a model-provider abstraction (ADR-0008). Agents never get unrestricted access to application data or arbitrary tools.

## Hierarchical agent roster

### Station Orchestrator
Coordinates specialised agents, manages tasks, assembles findings, controls workflow state. The only agent allowed to invoke other agents; the only agent that writes to shared workflow state.

### Planning Agent
Investigates forecast volumes, truck arrivals, capacity, and planning scenarios. Reads from Layer 3 (analytics/simulation); never writes staffing decisions directly — produces a recommendation for human review (Layer 5).

### Investigation Agent
Investigates operational problems using evidence from relevant domain services. General-purpose evidence gatherer the Orchestrator dispatches for "what happened" questions.

### Flow Intelligence Agent
Analyses induct, sortation, stow, WIPS, jackpot, and capacity constraints (Cycle 1 domain).

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

## Model-provider abstraction

Agent code calls an internal `LLMProvider` interface (ADR-0008), never a vendor SDK directly. Claude Code/Claude CLI is the tool used to *build* StationOS during development; it is explicitly not assumed to be the production inference path, and no agent logic may depend on a developer's personal subscription being available at runtime.

## Memory

Deferred in detail to Milestone 5, but the shape: agents get per-investigation working memory (scoped to one orchestration run, checkpointed) and the Orchestrator may persist decision/outcome records (Layer 5 audit) that a future investigation can query as evidence — this is explicitly *retrieval of past recorded decisions*, not an opaque long-term memory blob an agent writes to freely.

## What's explicitly out of scope for agents

- Taking any action with real-world effect (dispatch, workforce assignment, parcel routing) directly. Agents produce recommendations; Layer 5 governs whether/how a human acts on them.
- Treating an RL policy's output as agent-generated evidence without labeling it as what it is (a policy recommendation, evaluated in simulation) — see `docs/RL_ENVIRONMENT_SPEC.md` and `docs/SYSTEM_ARCHITECTURE.md` on keeping the two sub-layers interoperable but distinct.
