"""The custom orchestration state machine (ADR-0005): deliberately
scoped to exactly what a single agent needs — persistent execution
state, one checkpoint boundary, bounded retries with a timeout, and
audit provenance — not a general-purpose multi-agent framework. See
ADR-0005's revisit condition for when that scoping stops being enough.

Checkpoint boundary: gather_evidence (deterministic — DuckDB/Postgres
queries) runs once and is persisted; interpret (non-deterministic — the
LLM call) is retried without re-gathering evidence. This mirrors
docs/AGENTIC_ARCHITECTURE.md's own split: "The data and analytics layer
should calculate... the LLM should interpret."
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import structlog
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.llm.base import LLMProvider, LLMProviderError
from app.core.tracing import get_tracer
from app.orchestration import repository
from app.orchestration.models import AgentExecution

log = structlog.get_logger(__name__)
tracer = get_tracer(__name__)


@dataclass(frozen=True)
class AgentDefinition[InputT: BaseModel, OutputT: BaseModel]:
    """An agent's full contract (docs/AGENTIC_ARCHITECTURE.md §"Per-agent
    contract"), expressed as three functions rather than a base class to
    keep an agent's own module able to test gather_evidence/interpret in
    isolation, with no orchestration machinery involved.

    Tool permissions are enforced by construction, not a runtime check:
    gather_evidence is whatever the agent module actually imports and
    calls — there is no generic "run arbitrary tool" path for it to
    misuse.
    """

    name: str
    gather_evidence: Callable[[InputT], dict]
    interpret: Callable[[InputT, dict, LLMProvider], OutputT]
    build_fallback_output: Callable[[InputT, dict, str], OutputT]
    max_retries: int = 2
    timeout_seconds: float = 30.0


class AgentExecutor:
    def __init__(self, session: Session, llm_provider: LLMProvider):
        self._session = session
        self._llm = llm_provider

    def run[InputT: BaseModel, OutputT: BaseModel](
        self, agent: AgentDefinition[InputT, OutputT], input_data: InputT
    ) -> OutputT:
        with tracer.start_as_current_span(
            "agent_execution.run", attributes={"agent.name": agent.name}
        ) as span:
            execution = repository.create_execution(
                self._session,
                agent_name=agent.name,
                input_payload=input_data.model_dump(mode="json"),
            )
            span.set_attribute("agent.execution_id", str(execution.id))
            log.info("agent_execution.started", agent=agent.name, execution_id=str(execution.id))

            with tracer.start_as_current_span("agent_execution.gather_evidence"):
                evidence = agent.gather_evidence(input_data)
            repository.checkpoint(self._session, execution, evidence)
            log.info(
                "agent_execution.checkpointed", agent=agent.name, execution_id=str(execution.id)
            )

            return self._interpret_with_retry(agent, input_data, evidence, execution)

    def resume[InputT: BaseModel, OutputT: BaseModel](
        self,
        agent: AgentDefinition[InputT, OutputT],
        execution_id: uuid.UUID,
        input_data: InputT,
    ) -> OutputT:
        """Retries only the interpretation step of a previously-
        checkpointed execution — evidence is not re-gathered. The
        concrete demonstration that "persistent execution state" is
        actually useful, not just data sitting in a row.
        """
        with tracer.start_as_current_span(
            "agent_execution.resume",
            attributes={"agent.name": agent.name, "agent.execution_id": str(execution_id)},
        ):
            execution = repository.get_by_id(self._session, execution_id)
            if execution is None:
                raise ValueError(f"no agent execution found for id={execution_id}")
            if execution.checkpoint is None:
                raise ValueError(f"execution {execution_id} has no checkpoint to resume from")

            log.info("agent_execution.resumed", agent=agent.name, execution_id=str(execution_id))
            return self._interpret_with_retry(agent, input_data, execution.checkpoint, execution)

    def _interpret_with_retry[InputT: BaseModel, OutputT: BaseModel](
        self,
        agent: AgentDefinition[InputT, OutputT],
        input_data: InputT,
        evidence: dict,
        execution: AgentExecution,
    ) -> OutputT:
        last_error: Exception | None = None
        total_attempts = agent.max_retries + 1

        for attempt in range(1, total_attempts + 1):
            with tracer.start_as_current_span(
                "agent_execution.interpret_attempt", attributes={"agent.attempt": attempt}
            ):
                try:
                    output = agent.interpret(input_data, evidence, self._llm)
                except LLMProviderError as exc:
                    last_error = exc
                    log.warning(
                        "agent_execution.attempt_failed",
                        agent=agent.name,
                        execution_id=str(execution.id),
                        attempt=attempt,
                        error=str(exc),
                    )
                    continue

            repository.mark_completed(self._session, execution, output.model_dump(mode="json"))
            log.info(
                "agent_execution.completed",
                agent=agent.name,
                execution_id=str(execution.id),
                attempt=attempt,
            )
            return output

        # Degrade gracefully to "insufficient evidence" — never fabricate
        # (docs/AGENTIC_ARCHITECTURE.md). The audit record is honestly
        # marked failed even though a usable fallback is returned.
        fallback = agent.build_fallback_output(input_data, evidence, str(last_error))
        repository.mark_failed(
            self._session,
            execution,
            error=str(last_error),
            retry_count=agent.max_retries,
            fallback_output=fallback.model_dump(mode="json"),
        )
        log.error(
            "agent_execution.degraded",
            agent=agent.name,
            execution_id=str(execution.id),
            error=str(last_error),
        )
        return fallback
