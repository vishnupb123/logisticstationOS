# ADR-0008: LLM provider abstraction

**Status**: Accepted

## Context

Claude CLI/Claude Code is being used as the *development* tool to build StationOS. The application itself, once it has agents, needs production inference that does not depend on a developer's personal subscription or a single hardcoded vendor SDK call.

## Options considered

1. **Call a specific vendor's SDK directly from agent/business logic.** Rejected: couples the application to one vendor's API shape and to whatever auth context is available at runtime (which, left unaddressed, risks ending up being a developer's personal credentials — unacceptable for anything meant to run as a service).
2. **Adopt a third-party multi-provider framework as the abstraction.** Possible later, but premature to adopt before there's a single working agent to validate the abstraction's shape against — mirrors the reasoning in ADR-0005 about not adopting a framework before the requirement is concrete.
3. **Define an internal `LLMProvider` interface** (structured-output-capable completion call, with typed request/response, independent of any one vendor), implemented by one or more concrete provider adapters chosen later. Chosen.

## Decision

All agent/business logic calls an internal `LLMProvider` interface (location: alongside `backend/app/agents/` or a dedicated `backend/app/core/llm/` module, exact placement TBD at Milestone 5 implementation time), never a vendor SDK directly. Claude Code's availability during development is explicitly not a dependency the running application can assume.

## Rationale

This is a governance requirement as much as a technical one: "the application must not depend on a developer's Claude Max subscription for production inference" is stated directly in the project's founding brief. An interface boundary is the standard way to make that true in code, not just in intent.

## Consequences

- Milestone 5 must select and implement at least one concrete provider adapter before any agent can run for real — this is an explicit open question (`docs/OPEN_QUESTIONS.md`), not resolved by this ADR.
- Swapping or adding a provider later means writing a new adapter, not touching agent logic.
- Structured-output support (for the typed evidence objects in `docs/AGENTIC_ARCHITECTURE.md`) must be representable through the interface from day one, not added later as a special case.

## Risks

- Designing an interface before a concrete provider is chosen risks guessing wrong about what the abstraction needs to expose — mitigated by keeping the interface minimal and revising it against the first real adapter rather than over-speculating now.

## Revisit conditions

Revisit the interface shape once the first concrete provider adapter is implemented and its fit against real usage is known.
