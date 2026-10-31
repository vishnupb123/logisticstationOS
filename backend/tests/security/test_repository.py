"""DB-dependent tests for DecisionRecord persistence (ADR-0009) — real
Postgres, not mocked. The guards under test
(_require_pending / the APPROVED check in record_observed_outcome /
the RBAC check in approve_decision-reject_decision / the shadow-mode
dead end) are the literal code form of "no path lets a recommendation
become acted on without approval," now including who is allowed to
approve it (Milestone 9).
"""

import pytest
from pydantic import ValidationError

from app.security.models import DecisionStatus
from app.security.rbac import RBACError, Role
from app.security.repository import (
    approve_decision,
    create_decision_record,
    get_by_id,
    list_decisions,
    record_observed_outcome,
    reject_decision,
)

_CANDIDATES = [
    {
        "name": "status_quo",
        "description": "uniform priority",
        "priority_weights": {"A1": 0.5},
        "evaluation": {},
    },
    {
        "name": "tilted",
        "description": "tilted priority",
        "priority_weights": {"A1": 0.9},
        "evaluation": {},
    },
]


def _new_record(session, *, shadow: bool = False):
    return create_decision_record(
        session,
        decision_type="aisle_stow_priority",
        context={"trigger": "test"},
        evidence=[{"category": "observation", "summary": "test evidence"}],
        candidates=_CANDIDATES,
        policy_engine_result={"eligible": True, "violations": []},
        risk_evaluation={
            "blast_radius": "simulation_only",
            "reversible": True,
            "rationale": "test",
        },
        component_versions={"policy_engine": "2026-10-31.1"},
        shadow=shadow,
    )


def test_create_decision_record_starts_pending_approval(db_session):
    record = _new_record(db_session)

    assert record.status == DecisionStatus.PENDING_APPROVAL.value
    assert record.selected_candidate is None
    assert record.decided_at is None
    assert get_by_id(db_session, record.id) is not None


def test_create_decision_record_rejects_malformed_evidence(db_session):
    with pytest.raises(ValidationError):
        create_decision_record(
            db_session,
            decision_type="aisle_stow_priority",
            context={"trigger": "test"},
            evidence=[{"category": "not_a_real_category", "summary": "bad"}],
            candidates=_CANDIDATES,
            policy_engine_result={"eligible": True, "violations": []},
            risk_evaluation={
                "blast_radius": "simulation_only",
                "reversible": True,
                "rationale": "test",
            },
            component_versions={},
        )


def test_shadow_decision_is_created_with_shadow_status(db_session):
    record = _new_record(db_session, shadow=True)

    assert record.status == DecisionStatus.SHADOW.value


def test_approve_decision_sets_selection_role_and_timestamp(db_session):
    record = _new_record(db_session)

    approved = approve_decision(
        db_session,
        record,
        approved_by="demo-supervisor",
        approver_role=Role.SUPERVISOR,
        selected_candidate="tilted",
        rationale="lower simulated backlog",
    )

    assert approved.status == DecisionStatus.APPROVED.value
    assert approved.selected_candidate == "tilted"
    assert approved.approved_by == "demo-supervisor"
    assert approved.approver_role == Role.SUPERVISOR.value
    assert approved.decided_at is not None


def test_operator_cannot_approve_any_decision(db_session):
    record = _new_record(db_session)

    with pytest.raises(RBACError, match="operator"):
        approve_decision(
            db_session,
            record,
            approved_by="demo-operator",
            approver_role=Role.OPERATOR,
            selected_candidate="tilted",
            rationale="x",
        )


def test_admin_can_approve_any_eligible_decision_type(db_session):
    record = _new_record(db_session)

    approved = approve_decision(
        db_session,
        record,
        approved_by="demo-admin",
        approver_role=Role.ADMIN,
        selected_candidate="tilted",
        rationale="x",
    )

    assert approved.approver_role == Role.ADMIN.value


def test_a_shadow_decision_can_never_be_approved_even_by_an_admin(db_session):
    record = _new_record(db_session, shadow=True)

    with pytest.raises(ValueError, match="already"):
        approve_decision(
            db_session,
            record,
            approved_by="demo-admin",
            approver_role=Role.ADMIN,
            selected_candidate="tilted",
            rationale="x",
        )


def test_approve_decision_rejects_unknown_candidate(db_session):
    record = _new_record(db_session)

    with pytest.raises(ValueError, match="not one of this decision's candidates"):
        approve_decision(
            db_session,
            record,
            approved_by="demo-supervisor",
            approver_role=Role.SUPERVISOR,
            selected_candidate="does_not_exist",
            rationale="x",
        )


def test_cannot_re_decide_an_already_approved_record(db_session):
    record = _new_record(db_session)
    approve_decision(
        db_session,
        record,
        approved_by="a",
        approver_role=Role.SUPERVISOR,
        selected_candidate="status_quo",
        rationale="x",
    )

    with pytest.raises(ValueError, match="already"):
        approve_decision(
            db_session,
            record,
            approved_by="b",
            approver_role=Role.SUPERVISOR,
            selected_candidate="tilted",
            rationale="y",
        )


def test_reject_decision_sets_rejected_status(db_session):
    record = _new_record(db_session)

    rejected = reject_decision(
        db_session,
        record,
        approved_by="demo-supervisor",
        approver_role=Role.SUPERVISOR,
        rationale="not worth the complexity",
    )

    assert rejected.status == DecisionStatus.REJECTED.value
    assert rejected.selected_candidate is None


def test_operator_cannot_reject(db_session):
    record = _new_record(db_session)

    with pytest.raises(RBACError):
        reject_decision(
            db_session,
            record,
            approved_by="demo-operator",
            approver_role=Role.OPERATOR,
            rationale="x",
        )


def test_observed_outcome_cannot_be_recorded_without_approval(db_session):
    record = _new_record(db_session)

    with pytest.raises(ValueError, match="not approved"):
        record_observed_outcome(db_session, record, {"stowed": 10})


def test_observed_outcome_cannot_be_recorded_for_a_rejected_decision(db_session):
    record = _new_record(db_session)
    reject_decision(
        db_session, record, approved_by="a", approver_role=Role.SUPERVISOR, rationale="x"
    )

    with pytest.raises(ValueError, match="not approved"):
        record_observed_outcome(db_session, record, {"stowed": 10})


def test_observed_outcome_recorded_after_approval(db_session):
    record = _new_record(db_session)
    approve_decision(
        db_session,
        record,
        approved_by="a",
        approver_role=Role.SUPERVISOR,
        selected_candidate="status_quo",
        rationale="x",
    )

    outcome_record = record_observed_outcome(db_session, record, {"stowed": 42})

    assert outcome_record.observed_outcome == {"stowed": 42}
    assert outcome_record.outcome_recorded_at is not None


def test_list_decisions_filters_by_status(db_session):
    pending = _new_record(db_session)
    approved = _new_record(db_session)
    approve_decision(
        db_session,
        approved,
        approved_by="a",
        approver_role=Role.SUPERVISOR,
        selected_candidate="status_quo",
        rationale="x",
    )

    pending_only = list_decisions(db_session, status=DecisionStatus.PENDING_APPROVAL.value)
    assert pending.id in {r.id for r in pending_only}
    assert approved.id not in {r.id for r in pending_only}
