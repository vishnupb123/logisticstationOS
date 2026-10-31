# ADR-0005: Agent orchestration approach

**Status**: Accepted (narrow scope) — framework choice open for revisit

## Context

The agentic layer (`docs/AGENTIC_ARCHITECTURE.md`) needs an orchestration mechanism that supports typed tools, structured outputs, persistent execution state, checkpointing, retries/timeouts, and evidence provenance, for a small hierarchical set of agents (Orchestrator + five specialists).

## Options considered

1. **LangGraph.** A purpose-built graph-based agent orchestration framework with checkpointing support built in. Strong fit on paper, but adopting it now means taking on a framework dependency and its abstractions before StationOS has even one working agent to validate the fit against.
2. **A carefully designed custom state machine.** More upfront work per feature (checkpointing, retries have to be built), but total control over the evidence-provenance and tool-permission model this project requires, and no framework lock-in while the actual shape of "an agent" in this domain is still being learned.
3. **No formal orchestration — ad hoc function calls between agent implementations.** Rejected outright: fails the "persistent execution state, checkpointing, retries" requirement by construction.

## Decision

Start with a custom, purpose-built state machine in `backend/app/orchestration/`, scoped to exactly what the five-agent roster needs (not a general-purpose agent framework). Re-evaluate LangGraph (or similar) once there are at least two real agents exercising cross-agent coordination and checkpoint/resume behavior, so the comparison is grounded in actual requirements rather than a framework's feature list.

## Rationale

"Evaluate alternatives before committing to a framework" is an explicit project principle. A custom implementation forces explicit answers to the evidence-provenance and tool-permission questions this project cares about most, rather than inheriting a framework's defaults. The cost is more code to maintain; that cost is accepted while the agent roster is small (Milestone 5 ships exactly one agent).

## Consequences

- Milestone 5 includes building orchestration primitives (checkpointing, retry/timeout policy) as part of the first agent's delivery, not as separately-provided infrastructure.
- The custom implementation's interfaces should be designed so that swapping in LangGraph later (if the revisit concludes that's right) doesn't require rewriting agent definitions — a thin boundary, not agents calling orchestration internals directly.

## Risks

- Building and maintaining orchestration primitives in-house is real ongoing cost; if agent count/complexity grows faster than expected, this could become the wrong trade.

## Revisit conditions

Revisit once 2+ agents need cross-agent checkpoint/resume behavior the custom machine is clearly straining to support, or once the orchestration code itself becomes a maintenance burden disproportionate to the agent roster's size.
