"""Typed persistence functions for DecisionRecord (ADR-0009). Three
guards that make "no path lets a recommendation become acted on
without approval" a correctness property of the code, not a
convention:

1. `approve_decision`/`reject_decision` refuse anything not in
   PENDING_APPROVAL — no re-deciding a decided record, and (since a
   shadow-mode record is created with status SHADOW, never
   PENDING_APPROVAL) no deciding a shadow-mode record either, with no
   separate check needed for that case.
2. Both also now require (Milestone 9) a valid `app/security/rbac.py::Role`
   that is checked against the decision's own `decision_type` before
   anything is mutated — the piece ADR-0009's Consequences flagged as
   still missing after Milestone 7.
3. `record_observed_outcome` refuses anything not in APPROVED — no
   recording an outcome for a decision that was never approved.

`create_decision_record` also re-validates every JSONB-bound argument
against its real Pydantic schema (Milestone 9: "data validation") —
a malformed caller can no longer write structurally-invalid data
straight into the permanent audit record; it gets a loud
`pydantic.ValidationError` instead.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agents.schemas import Finding
from app.security import rbac
from app.security.models import DecisionRecord, DecisionStatus
from app.security.policy_engine import CandidateRecord, PolicyEngineResult
from app.security.rbac import Role
from app.security.risk import RiskEvaluation


def create_decision_record(
    session: Session,
    *,
    decision_type: str,
    context: dict,
    evidence: list[dict],
    candidates: list[dict],
    policy_engine_result: dict,
    risk_evaluation: dict,
    component_versions: dict,
    shadow: bool = False,
) -> DecisionRecord:
    """Created as PENDING_APPROVAL, or SHADOW if `shadow=True` — there
    is no way to construct one already "approved." A shadow-mode
    record is a dead end by construction: every status-changing
    function below only accepts PENDING_APPROVAL as a starting point.
    """
    validated_evidence = [Finding.model_validate(e) for e in evidence]
    validated_candidates = [CandidateRecord.model_validate(c) for c in candidates]
    validated_policy_result = PolicyEngineResult.model_validate(policy_engine_result)
    validated_risk = RiskEvaluation.model_validate(risk_evaluation)

    status = DecisionStatus.SHADOW if shadow else DecisionStatus.PENDING_APPROVAL
    record = DecisionRecord(
        decision_type=decision_type,
        status=status.value,
        context=context,
        evidence=[f.model_dump(mode="json") for f in validated_evidence],
        candidates=[c.model_dump(mode="json") for c in validated_candidates],
        policy_engine_result=validated_policy_result.model_dump(mode="json"),
        risk_evaluation=validated_risk.model_dump(mode="json"),
        component_versions=component_versions,
    )
    session.add(record)
    session.flush()
    return record


def _require_pending(record: DecisionRecord) -> None:
    if record.status != DecisionStatus.PENDING_APPROVAL.value:
        raise ValueError(
            f"decision {record.id} is already {record.status!r} — cannot be re-decided"
        )


def approve_decision(
    session: Session,
    record: DecisionRecord,
    *,
    approved_by: str,
    approver_role: Role,
    selected_candidate: str,
    rationale: str,
) -> DecisionRecord:
    _require_pending(record)
    rbac.check_can_approve(approver_role, record.decision_type)
    candidate_names = {c["name"] for c in record.candidates}
    if selected_candidate not in candidate_names:
        raise ValueError(
            f"{selected_candidate!r} is not one of this decision's candidates: {candidate_names}"
        )
    record.status = DecisionStatus.APPROVED.value
    record.selected_candidate = selected_candidate
    record.approved_by = approved_by
    record.approver_role = approver_role.value
    record.approval_rationale = rationale
    record.decided_at = datetime.now(UTC)
    session.flush()
    return record


def reject_decision(
    session: Session,
    record: DecisionRecord,
    *,
    approved_by: str,
    approver_role: Role,
    rationale: str,
) -> DecisionRecord:
    _require_pending(record)
    rbac.check_can_approve(approver_role, record.decision_type)
    record.status = DecisionStatus.REJECTED.value
    record.approved_by = approved_by
    record.approver_role = approver_role.value
    record.approval_rationale = rationale
    record.decided_at = datetime.now(UTC)
    session.flush()
    return record


def record_observed_outcome(
    session: Session, record: DecisionRecord, outcome: dict
) -> DecisionRecord:
    """The "acted on" effect — deliberately gated on APPROVED status so
    this can never be called for a pending or rejected decision. In
    this synthetic system "observed outcome" means a fresh simulation
    run with the approved candidate's weights (see
    app/security/decision_service.py::observe_outcome) — never a claim
    about a real operational result, since there is no live system.
    """
    if record.status != DecisionStatus.APPROVED.value:
        raise ValueError(
            f"decision {record.id} is {record.status!r}, not approved — "
            "an outcome cannot be recorded for a decision that was never acted on"
        )
    record.observed_outcome = outcome
    record.outcome_recorded_at = datetime.now(UTC)
    session.flush()
    return record


def get_by_id(session: Session, decision_id: uuid.UUID) -> DecisionRecord | None:
    return session.get(DecisionRecord, decision_id)


def list_decisions(session: Session, *, status: str | None = None) -> list[DecisionRecord]:
    query = session.query(DecisionRecord)
    if status is not None:
        query = query.filter(DecisionRecord.status == status)
    return query.order_by(DecisionRecord.created_at.desc()).all()
