"""The AI investigations view (Milestone 10) — lists and runs Flow
Intelligence Agent executions (Milestone 5). `POST .../run` uses the
real `OllamaProvider` (never `FakeLLMProvider`, which is test-only and
"never a silent runtime default" per `docs/AGENTIC_ARCHITECTURE.md`)
— if no Ollama server is reachable, `AgentExecutor`'s existing,
already-tested fallback path kicks in (deterministic findings plus
`interpretation_error` set), exactly the same way it would from any
other caller. This endpoint adds no new failure-handling logic.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.flow_intelligence.agent import AGENT
from app.agents.flow_intelligence.schemas import FlowIntelligenceInput
from app.core.config import get_settings
from app.core.llm.ollama import OllamaProvider
from app.db.duckdb import resolve_duckdb_path
from app.db.postgres import get_db
from app.orchestration import repository
from app.orchestration.models import AgentExecution
from app.orchestration.runner import AgentExecutor
from app.schemas.agents import AgentExecutionDetail, AgentExecutionSummary

router = APIRouter(prefix="/agents/flow-intelligence", tags=["agents"])

_AGENT_NAME = AGENT.name


@router.get("/executions", response_model=list[AgentExecutionSummary])
def list_executions(db: Session = Depends(get_db)) -> list[AgentExecutionSummary]:
    executions = repository.list_executions(db, agent_name=_AGENT_NAME)
    return [AgentExecutionSummary.model_validate(e) for e in executions]


@router.get("/executions/{execution_id}", response_model=AgentExecutionDetail)
def get_execution(execution_id: uuid.UUID, db: Session = Depends(get_db)) -> AgentExecutionDetail:
    execution = repository.get_by_id(db, execution_id)
    if execution is None or execution.agent_name != _AGENT_NAME:
        raise HTTPException(status_code=404, detail=f"no execution found for id={execution_id}")
    return AgentExecutionDetail.model_validate(execution)


@router.post("/run", response_model=AgentExecutionDetail)
def run(db: Session = Depends(get_db)) -> AgentExecutionDetail:
    settings = get_settings()
    try:
        duckdb_path = str(resolve_duckdb_path())
        llm = OllamaProvider(settings.ollama_base_url, settings.ollama_model)
        executor = AgentExecutor(db, llm)
        output = executor.run(AGENT, FlowIntelligenceInput(duckdb_path=duckdb_path))
    except Exception:
        db.rollback()
        raise
    db.commit()

    execution = (
        db.query(AgentExecution)
        .filter(AgentExecution.agent_name == _AGENT_NAME)
        .order_by(AgentExecution.created_at.desc())
        .first()
    )
    assert execution is not None  # AgentExecutor.run always persists one

    detail = AgentExecutionDetail.model_validate(execution)
    # On an LLM-interpretation fallback, AgentExecutor (Milestone 5,
    # app/orchestration/runner.py) marks the execution FAILED and
    # records `error`, but deliberately never writes the fallback
    # output into the persisted row's `output` column — only a
    # successful run does that (`mark_completed`). The caller still
    # gets a real, non-fabricated result (deterministic findings,
    # `interpretation_error` set) either way, so this endpoint always
    # returns the actual in-memory result rather than only what
    # happened to get persisted.
    detail.output = output.model_dump(mode="json")
    return detail
