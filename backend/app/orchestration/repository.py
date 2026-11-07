import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.orchestration.models import AgentExecution, AgentExecutionStatus


def create_execution(session: Session, *, agent_name: str, input_payload: dict) -> AgentExecution:
    execution = AgentExecution(
        agent_name=agent_name,
        status=AgentExecutionStatus.RUNNING.value,
        input=input_payload,
    )
    session.add(execution)
    session.flush()
    return execution


def checkpoint(session: Session, execution: AgentExecution, checkpoint_payload: dict) -> None:
    execution.checkpoint = checkpoint_payload
    session.flush()


def mark_completed(session: Session, execution: AgentExecution, output_payload: dict) -> None:
    execution.status = AgentExecutionStatus.COMPLETED.value
    execution.output = output_payload
    execution.completed_at = datetime.now(UTC)
    session.flush()


def mark_failed(
    session: Session,
    execution: AgentExecution,
    *,
    error: str,
    retry_count: int,
    fallback_output: dict | None = None,
) -> None:
    """Status stays FAILED (the LLM interpretation genuinely failed), but
    the degraded, deterministic fallback result the caller actually
    received is persisted too — otherwise the audit row can't show what
    was returned, and every reader (API, UI) needed its own workaround.
    """
    execution.status = AgentExecutionStatus.FAILED.value
    execution.error = error
    execution.output = fallback_output
    execution.retry_count = retry_count
    execution.completed_at = datetime.now(UTC)
    session.flush()


def get_by_id(session: Session, execution_id: uuid.UUID) -> AgentExecution | None:
    return session.get(AgentExecution, execution_id)


def list_executions(
    session: Session, *, agent_name: str | None = None
) -> list[AgentExecution]:
    query = session.query(AgentExecution)
    if agent_name is not None:
        query = query.filter(AgentExecution.agent_name == agent_name)
    return query.order_by(AgentExecution.created_at.desc()).all()
