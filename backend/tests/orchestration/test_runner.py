"""DB-dependent tests for the orchestration state machine (ADR-0005) —
real Postgres, not mocked, same as every other persistence test in this
suite. Uses a trivial test agent, not the real Flow Intelligence Agent,
so these are purely about the orchestration mechanics (checkpointing,
retry, resume, audit) — see tests/agents/flow_intelligence/ for the
real agent's own evaluation tests.
"""

from pydantic import BaseModel

from app.core.llm.base import LLMProviderError
from app.core.llm.fake import FakeLLMProvider
from app.orchestration.models import AgentExecution, AgentExecutionStatus
from app.orchestration.repository import get_by_id
from app.orchestration.runner import AgentDefinition, AgentExecutor


class _Input(BaseModel):
    value: int


class _Output(BaseModel):
    result: int


def _gather_evidence(input_data: _Input) -> dict:
    return {"doubled": input_data.value * 2}


def _interpret(input_data: _Input, evidence: dict, llm) -> _Output:
    return llm.complete_structured(
        system_prompt="sys", user_prompt=f"evidence={evidence}", response_model=_Output
    )


def _build_fallback(input_data: _Input, evidence: dict, error: str) -> _Output:
    return _Output(result=evidence["doubled"])


def _agent(name: str = "test_agent", max_retries: int = 2) -> AgentDefinition[_Input, _Output]:
    return AgentDefinition(
        name=name,
        gather_evidence=_gather_evidence,
        interpret=_interpret,
        build_fallback_output=_build_fallback,
        max_retries=max_retries,
    )


def _execution_for(session, agent_name: str) -> AgentExecution:
    return (
        session.query(AgentExecution)
        .filter(AgentExecution.agent_name == agent_name)
        .order_by(AgentExecution.created_at.desc())
        .first()
    )


def test_run_persists_a_completed_execution(db_session):
    llm = FakeLLMProvider([_Output(result=42)])
    executor = AgentExecutor(db_session, llm)

    output = executor.run(_agent(), _Input(value=21))

    assert output == _Output(result=42)
    assert len(llm.calls) == 1


def test_execution_checkpoints_evidence_before_interpretation(db_session):
    llm = FakeLLMProvider([_Output(result=1)])
    executor = AgentExecutor(db_session, llm)

    output = executor.run(_agent("checkpoint_agent"), _Input(value=10))

    execution = _execution_for(db_session, "checkpoint_agent")
    assert execution.checkpoint == {"doubled": 20}
    assert execution.status == AgentExecutionStatus.COMPLETED.value
    assert execution.output == output.model_dump(mode="json")
    assert execution.input == {"value": 10}


def test_retries_on_provider_error_then_succeeds(db_session):
    llm = FakeLLMProvider([LLMProviderError("transient"), _Output(result=99)])
    executor = AgentExecutor(db_session, llm)

    output = executor.run(_agent("retry_agent", max_retries=2), _Input(value=1))

    assert output == _Output(result=99)
    assert len(llm.calls) == 2  # one failure, one success — evidence gathered only once


def test_exhausted_retries_returns_fallback_and_marks_execution_failed(db_session):
    llm = FakeLLMProvider(
        [LLMProviderError("down"), LLMProviderError("still down"), LLMProviderError("still down")]
    )
    executor = AgentExecutor(db_session, llm)

    output = executor.run(_agent("failing_agent", max_retries=2), _Input(value=5))

    # Degrades gracefully: deterministic evidence-derived fallback, not a crash.
    assert output == _Output(result=10)

    execution = _execution_for(db_session, "failing_agent")
    assert execution.status == AgentExecutionStatus.FAILED.value
    assert execution.error is not None
    assert execution.retry_count == 2
    # The degraded result the caller received is persisted on the audit
    # row too, not silently dropped (previously a documented gap).
    assert execution.output == output.model_dump(mode="json")


def test_resume_reuses_checkpoint_without_regathering_evidence(db_session):
    call_count = {"n": 0}

    def counting_gather_evidence(input_data: _Input) -> dict:
        call_count["n"] += 1
        return {"doubled": input_data.value * 2}

    agent = AgentDefinition(
        name="resumable_agent",
        gather_evidence=counting_gather_evidence,
        interpret=_interpret,
        build_fallback_output=_build_fallback,
        max_retries=0,
    )

    failing_llm = FakeLLMProvider([LLMProviderError("down")])
    executor = AgentExecutor(db_session, failing_llm)
    first_output = executor.run(agent, _Input(value=7))
    assert first_output == _Output(result=14)  # fallback
    assert call_count["n"] == 1

    execution = get_by_id(db_session, _execution_for(db_session, "resumable_agent").id)
    assert execution.status == AgentExecutionStatus.FAILED.value

    succeeding_llm = FakeLLMProvider([_Output(result=100)])
    resumed_executor = AgentExecutor(db_session, succeeding_llm)
    resumed_output = resumed_executor.resume(agent, execution.id, _Input(value=7))

    assert resumed_output == _Output(result=100)
    assert call_count["n"] == 1, "resume must not re-run gather_evidence"
