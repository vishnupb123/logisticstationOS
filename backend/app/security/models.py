"""The decision record (Milestone 7, ADR-0009): the persistent form of
docs/SECURITY_AND_GOVERNANCE.md's "Decision governance pipeline" —
context, evidence, candidates, policy-engine result, risk evaluation,
approval, and observed outcome, all on one row, so the whole pipeline
for one decision can be queried end to end. Status transitions are
one-way (pending_approval -> approved/rejected, or shadow -> nowhere)
and enforced by app/security/repository.py, not by this model alone —
a row's status isn't guidance, the repository functions are the only
place that are allowed to change it.

SHADOW (Milestone 9: "shadow-mode evaluation support, keeping
recommendations visibly separate from anything executed") is a
terminal status, not a stepping stone to pending_approval — a decision
created in shadow mode can never be approved, rejected, or have an
outcome recorded; `app/security/repository.py`'s existing
`_require_pending` guard already refuses any status other than
`pending_approval`, so shadow decisions are excluded automatically,
with no separate check to maintain.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class DecisionStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SHADOW = "shadow"


class DecisionRecord(Base):
    __tablename__ = "decision_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    decision_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default=DecisionStatus.PENDING_APPROVAL.value)

    # Context: what triggered this decision (e.g. which agent run, which
    # scenario, in plain terms) — not itself evidence, just provenance.
    context: Mapped[dict] = mapped_column(JSONB)
    # Evidence: the Finding objects (app/agents/schemas.py) that justify
    # investigating this decision at all — serialized, not re-derived.
    evidence: Mapped[list] = mapped_column(JSONB)
    # Candidates: named interventions plus their simulated evaluation —
    # app/security/decision_service.py::CandidateEvaluation, serialized.
    candidates: Mapped[list] = mapped_column(JSONB)
    # app/security/policy_engine.py::PolicyEngineResult, serialized.
    policy_engine_result: Mapped[dict] = mapped_column(JSONB)
    # app/security/risk.py::RiskEvaluation, serialized.
    risk_evaluation: Mapped[dict] = mapped_column(JSONB)
    # Which version of each component (e.g. the policy engine) produced
    # this record — app/core/versioning.py's convention, stamped at
    # creation (Milestone 9: "model and policy versioning").
    component_versions: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Set only by approve_decision/reject_decision (app/security/repository.py).
    selected_candidate: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The app/security/rbac.py::Role the approver claimed and was
    # checked against (Milestone 9: "role-based access control") — set
    # alongside approved_by, never on its own.
    approver_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approval_rationale: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set only by record_observed_outcome, and only once status is
    # APPROVED — this is the structural form of ADR-0009's "no path lets
    # a recommendation become an acted-on decision without approval."
    observed_outcome: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
