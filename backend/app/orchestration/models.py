"""Persistent agent execution state (ADR-0005: "persistent execution
state, checkpointing" is a hard requirement, not optional). Also the
audit record each agent contract requires (docs/AGENTIC_ARCHITECTURE.md
§"Per-agent contract" — "Audit provenance: what gets logged per
invocation") — this row *is* that log entry, not a separate thing.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class AgentExecutionStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    #: Deterministic evidence + findings are complete, but the LLM
    #: interpretation step was unavailable/invalid after retries — the
    #: output is real and usable, just without the LLM narrative layer.
    DEGRADED = "degraded"
    #: Evidence gathering itself raised — no usable output.
    FAILED = "failed"


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    input: Mapped[dict] = mapped_column(JSONB)
    # Set once the deterministic evidence-gathering step completes —
    # the checkpoint a retry of the (non-deterministic) interpretation
    # step resumes from, so a failed LLM call never re-queries evidence.
    checkpoint: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
