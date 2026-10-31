"""DB-dependent tests for DecisionRecord persistence (ADR-0009) — real
Postgres, not mocked. The two guards under test
(_require_pending/the APPROVED check in record_observed_outcome) are
the literal code form of "no path lets a recommendation become acted
on without approval."
"""

import pytest

from app.security.models import DecisionStatus
from app.security.repository import (
    approve_decision,
    create_decision_record,
    get_by_id,
    list_decisions,
    record_observed_outcome,
    reject_decision,
)

_CANDIDATES = [
    {"name": "status_quo", "priority_weights": {"A1": 0.5}},
    {"name": "tilted", "priority_weights": {"A1": 0.9}},
]


def _new_record(session):
    return create_decision_record(
        session,
        decision_type="aisle_stow_priority",
        context={"trigger": "test"},
        evidence=[{"category": "observation", "summary": "test evidence"}],
        candidates=_CANDIDATES,
        policy_engine_result={"eligible": True, "violations": []},
        risk_evaluation={"blast_radius": "simulation_only", "reversible": True},
    )


def test_create_decision_record_starts_pending_approval(db_session):
    record = _new_record(db_session)

    assert record.status == DecisionStatus.PENDING_APPROVAL.value
    assert record.selected_candidate is None
    assert record.decided_at is None
    assert get_by_id(db_session, record.id) is not None


def test_approve_decision_sets_selection_and_timestamp(db_session):
    record = _new_record(db_session)

    approved = approve_decision(
        db_session,
        record,
        approved_by="demo-operator",
        selected_candidate="tilted",
        rationale="lower simulated backlog",
    )

    assert approved.status == DecisionStatus.APPROVED.value
    assert approved.selected_candidate == "tilted"
    assert approved.approved_by == "demo-operator"
    assert approved.decided_at is not None


def test_approve_decision_rejects_unknown_candidate(db_session):
    record = _new_record(db_session)

    with pytest.raises(ValueError, match="not one of this decision's candidates"):
        approve_decision(
            db_session,
            record,
            approved_by="demo-operator",
            selected_candidate="does_not_exist",
            rationale="x",
        )


def test_cannot_re_decide_an_already_approved_record(db_session):
    record = _new_record(db_session)
    approve_decision(
        db_session, record, approved_by="a", selected_candidate="status_quo", rationale="x"
    )

    with pytest.raises(ValueError, match="already"):
        approve_decision(
            db_session, record, approved_by="b", selected_candidate="tilted", rationale="y"
        )


def test_reject_decision_sets_rejected_status(db_session):
    record = _new_record(db_session)

    rejected = reject_decision(
        db_session, record, approved_by="demo-operator", rationale="not worth the complexity"
    )

    assert rejected.status == DecisionStatus.REJECTED.value
    assert rejected.selected_candidate is None


def test_observed_outcome_cannot_be_recorded_without_approval(db_session):
    record = _new_record(db_session)

    with pytest.raises(ValueError, match="not approved"):
        record_observed_outcome(db_session, record, {"stowed": 10})


def test_observed_outcome_cannot_be_recorded_for_a_rejected_decision(db_session):
    record = _new_record(db_session)
    reject_decision(db_session, record, approved_by="a", rationale="x")

    with pytest.raises(ValueError, match="not approved"):
        record_observed_outcome(db_session, record, {"stowed": 10})


def test_observed_outcome_recorded_after_approval(db_session):
    record = _new_record(db_session)
    approve_decision(
        db_session, record, approved_by="a", selected_candidate="status_quo", rationale="x"
    )

    outcome_record = record_observed_outcome(db_session, record, {"stowed": 42})

    assert outcome_record.observed_outcome == {"stowed": 42}
    assert outcome_record.outcome_recorded_at is not None


def test_list_decisions_filters_by_status(db_session):
    pending = _new_record(db_session)
    approved = _new_record(db_session)
    approve_decision(
        db_session, approved, approved_by="a", selected_candidate="status_quo", rationale="x"
    )

    pending_only = list_decisions(db_session, status=DecisionStatus.PENDING_APPROVAL.value)
    assert pending.id in {r.id for r in pending_only}
    assert approved.id not in {r.id for r in pending_only}
