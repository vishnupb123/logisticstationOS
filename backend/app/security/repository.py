"""Typed persistence functions for DecisionRecord (ADR-0009). The two
guards that make "no path lets a recommendation become acted on
without approval" a correctness property of the code, not a
convention: approve_decision/reject_decision refuse anything not in
PENDING_APPROVAL (no re-deciding a decided record), and
record_observed_outcome refuses anything not in APPROVED (no recording
an outcome for a decision that was never approved — there's nothing to
have "acted on" otherwise).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.security.models import DecisionRecord, DecisionStatus


def create_decision_record(
    session: Session,
    *,
    decision_type: str,
    context: dict,
    evidence: list[dict],
    candidates: list[dict],
    policy_engine_result: dict,
    risk_evaluation: dict,
) -> DecisionRecord:
    """Always created as PENDING_APPROVAL — there is no constructor
    argument for status, so a decision record cannot be created
    already "approved."
    """
    record = DecisionRecord(
        decision_type=decision_type,
        status=DecisionStatus.PENDING_APPROVAL.value,
        context=context,
        evidence=evidence,
        candidates=candidates,
        policy_engine_result=policy_engine_result,
        risk_evaluation=risk_evaluation,
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
    selected_candidate: str,
    rationale: str,
) -> DecisionRecord:
    _require_pending(record)
    candidate_names = {c["name"] for c in record.candidates}
    if selected_candidate not in candidate_names:
        raise ValueError(
            f"{selected_candidate!r} is not one of this decision's candidates: {candidate_names}"
        )
    record.status = DecisionStatus.APPROVED.value
    record.selected_candidate = selected_candidate
    record.approved_by = approved_by
    record.approval_rationale = rationale
    record.decided_at = datetime.now(UTC)
    session.flush()
    return record


def reject_decision(
    session: Session, record: DecisionRecord, *, approved_by: str, rationale: str
) -> DecisionRecord:
    _require_pending(record)
    record.status = DecisionStatus.REJECTED.value
    record.approved_by = approved_by
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
