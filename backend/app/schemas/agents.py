"""API-facing response models for the AI investigations view
(`backend/app/api/routes/agents.py`), wrapping `AgentExecution` ORM
rows (`app/orchestration/models.py`).
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AgentExecutionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_name: str
    status: str
    created_at: datetime
    completed_at: datetime | None


class AgentExecutionDetail(AgentExecutionSummary):
    input: dict
    checkpoint: dict | None
    output: dict | None
    error: str | None
    retry_count: int


# No request body: the agent always reads the server-configured
# analytics DuckDB path (app/db/duckdb.py::resolve_duckdb_path).
# Deliberately not an HTTP-supplied path — even a read-only DuckDB
# connection to an arbitrary caller-supplied path is an unnecessary
# arbitrary-file-access surface on an HTTP endpoint; the CLI equivalent
# (scripts/) can still take an explicit path, since that's a trusted
# local invocation, not a network-reachable one.
