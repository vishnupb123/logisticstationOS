"""The decision/audit history view (Milestone 10), and the one place
the frontend can actually drive the governance pipeline (propose,
approve, reject, observe outcome) rather than only display it.
`ProposeDecisionRequest.scenario`/`ObserveOutcomeRequest.scenario` are
shipped-scenario filenames, never filesystem paths (same boundary as
`app/api/routes/simulation.py`).

Error mapping, deliberately explicit rather than left to FastAPI's
default 500: `RBACError` (a role was checked and refused) -> 403;
the state-machine `ValueError`s from `app/security/repository.py`
(re-deciding a decided/shadow record, recording an outcome without
approval, an unknown candidate) -> 409, since they all mean "this
request conflicts with the record's current state," not "the request
itself was malformed."
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.schemas.decisions import (
    ApproveDecisionRequest,
    DecisionRecordOut,
    ObserveOutcomeRequest,
    ProposeDecisionRequest,
    RejectDecisionRequest,
)
from app.security import decision_service, repository
from app.security.rbac import RBACError
from app.simulation.config import resolve_shipped_scenario_path

router = APIRouter(prefix="/decisions", tags=["decisions"])


def _get_or_404(db: Session, decision_id: uuid.UUID):
    record = repository.get_by_id(db, decision_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no decision found for id={decision_id}")
    return record


@router.get("", response_model=list[DecisionRecordOut])
def list_decisions(status: str | None = None, db: Session = Depends(get_db)):
    return repository.list_decisions(db, status=status)


@router.get("/{decision_id}", response_model=DecisionRecordOut)
def get_decision(decision_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get_or_404(db, decision_id)


@router.post("", response_model=DecisionRecordOut)
def propose_decision(request: ProposeDecisionRequest, db: Session = Depends(get_db)):
    try:
        path = resolve_shipped_scenario_path(request.scenario)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    kwargs = dict(
        decision_type=request.decision_type,
        context=request.context,
        evidence=request.evidence,
        scenario_path=str(path),
        candidates=request.candidates,
        shadow=request.shadow,
    )
    if request.eval_seeds is not None:
        kwargs["eval_seeds"] = request.eval_seeds

    try:
        record = decision_service.propose_decision(db, **kwargs)
    except Exception:
        db.rollback()
        raise
    db.commit()
    return record


@router.post("/{decision_id}/approve", response_model=DecisionRecordOut)
def approve_decision(
    decision_id: uuid.UUID, request: ApproveDecisionRequest, db: Session = Depends(get_db)
):
    record = _get_or_404(db, decision_id)
    try:
        updated = repository.approve_decision(
            db,
            record,
            approved_by=request.approved_by,
            approver_role=request.approver_role,
            selected_candidate=request.selected_candidate,
            rationale=request.rationale,
        )
    except RBACError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return updated


@router.post("/{decision_id}/reject", response_model=DecisionRecordOut)
def reject_decision(
    decision_id: uuid.UUID, request: RejectDecisionRequest, db: Session = Depends(get_db)
):
    record = _get_or_404(db, decision_id)
    try:
        updated = repository.reject_decision(
            db,
            record,
            approved_by=request.approved_by,
            approver_role=request.approver_role,
            rationale=request.rationale,
        )
    except RBACError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return updated


@router.post("/{decision_id}/observe-outcome", response_model=DecisionRecordOut)
def observe_outcome(
    decision_id: uuid.UUID, request: ObserveOutcomeRequest, db: Session = Depends(get_db)
):
    record = _get_or_404(db, decision_id)
    try:
        path = resolve_shipped_scenario_path(request.scenario)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    kwargs = dict(scenario_path=str(path))
    if request.observe_seeds is not None:
        kwargs["observe_seeds"] = request.observe_seeds

    try:
        updated = decision_service.observe_outcome(db, record, **kwargs)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return updated
