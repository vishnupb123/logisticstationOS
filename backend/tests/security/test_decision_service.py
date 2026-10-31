"""Milestone 7 end-to-end: propose -> policy-engine/risk evaluation ->
approve -> observe outcome, against the real shipped RL scenario and a
real db_session — the literal exit-criteria scenario
(docs/ENGINEERING_ROADMAP.md Milestone 7: "a full decision record
(context -> evidence -> candidates -> simulation/policy evaluation ->
approval -> outcome) can be produced and queried end to end"), proven
here rather than only asserted in docs.
"""

from pathlib import Path

import pytest

from app.agents.schemas import EvidenceCategory, Finding
from app.security import decision_service
from app.security.models import DecisionStatus
from app.security.policy_engine import CandidateIntervention
from app.security.rbac import Role
from app.security.repository import approve_decision, get_by_id

_SCENARIO_PATH = str(
    Path(__file__).resolve().parents[3] / "simulation" / "scenarios" / "rl_stow_balancing.yaml"
)
_FAST_SEEDS = [1, 2]

_CANDIDATES = [
    CandidateIntervention(
        name="status_quo",
        description="uniform priority, no reallocation",
        priority_weights={f"A{i}": 0.5 for i in range(1, 7)},
    ),
    CandidateIntervention(
        name="favor_first_half",
        description="favor aisles A1-A3 over A4-A6",
        priority_weights={
            **{f"A{i}": 0.9 for i in range(1, 4)},
            **{f"A{i}": 0.1 for i in range(4, 7)},
        },
    ),
]

_EVIDENCE = [
    Finding(
        category=EvidenceCategory.OBSERVATION,
        summary="Jackpot backlog observed growing in the Flow Intelligence Agent's run.",
        supporting_evidence=["metric_jackpot_volume"],
    )
]


def test_evaluate_candidates_runs_real_simulation_for_each_candidate():
    results = decision_service.evaluate_candidates(
        _SCENARIO_PATH, _CANDIDATES, eval_seeds=_FAST_SEEDS
    )

    assert [r["name"] for r in results] == ["status_quo", "favor_first_half"]
    for result in results:
        assert len(result["evaluation"]["episodes"]) == len(_FAST_SEEDS)
        assert "max_jackpot_backlog_mean" in result["evaluation"]["aggregate"]


def test_propose_decision_produces_a_pending_record_with_full_pipeline(db_session):
    record = decision_service.propose_decision(
        db_session,
        decision_type="aisle_stow_priority",
        context={"trigger": "flow_intelligence_agent jackpot hypothesis"},
        evidence=_EVIDENCE,
        scenario_path=_SCENARIO_PATH,
        candidates=_CANDIDATES,
        eval_seeds=_FAST_SEEDS,
    )

    assert record.status == DecisionStatus.PENDING_APPROVAL.value
    assert len(record.candidates) == 2
    assert record.policy_engine_result["eligible"] is True
    assert record.risk_evaluation["blast_radius"] == "simulation_only"
    assert "policy_engine" in record.component_versions
    # Evidence now includes the original agent finding plus the
    # deterministic calculated/recommendation explanation findings.
    categories = [e["category"] for e in record.evidence]
    assert EvidenceCategory.OBSERVATION.value in categories
    assert EvidenceCategory.CALCULATED.value in categories
    assert EvidenceCategory.RECOMMENDATION.value in categories


def test_shadow_proposal_is_created_as_shadow_and_can_never_be_approved(db_session):
    record = decision_service.propose_decision(
        db_session,
        decision_type="aisle_stow_priority",
        context={"trigger": "trying out a new candidate shape"},
        evidence=_EVIDENCE,
        scenario_path=_SCENARIO_PATH,
        candidates=_CANDIDATES,
        eval_seeds=_FAST_SEEDS,
        shadow=True,
    )

    assert record.status == DecisionStatus.SHADOW.value

    with pytest.raises(ValueError, match="already"):
        approve_decision(
            db_session,
            record,
            approved_by="demo-admin",
            approver_role=Role.ADMIN,
            selected_candidate="favor_first_half",
            rationale="should never go through",
        )


def test_ineligible_decision_type_produces_no_recommendation(db_session):
    record = decision_service.propose_decision(
        db_session,
        decision_type="summon_more_stowers",
        context={"trigger": "test"},
        evidence=_EVIDENCE,
        scenario_path=_SCENARIO_PATH,
        candidates=_CANDIDATES,
        eval_seeds=_FAST_SEEDS,
    )

    assert record.policy_engine_result["eligible"] is False
    categories = [e["category"] for e in record.evidence]
    assert EvidenceCategory.RECOMMENDATION.value not in categories


def test_full_lifecycle_propose_approve_observe_outcome(db_session):
    record = decision_service.propose_decision(
        db_session,
        decision_type="aisle_stow_priority",
        context={"trigger": "test"},
        evidence=_EVIDENCE,
        scenario_path=_SCENARIO_PATH,
        candidates=_CANDIDATES,
        eval_seeds=_FAST_SEEDS,
    )

    approved = approve_decision(
        db_session,
        record,
        approved_by="demo-supervisor",
        approver_role=Role.SUPERVISOR,
        selected_candidate="favor_first_half",
        rationale="lower simulated backlog in the comparison",
    )

    outcome_record = decision_service.observe_outcome(
        db_session,
        approved,
        scenario_path=_SCENARIO_PATH,
        observe_seeds=_FAST_SEEDS,
    )

    assert outcome_record.observed_outcome is not None
    assert "aggregate" in outcome_record.observed_outcome
    assert outcome_record.outcome_recorded_at is not None

    # Queried back from scratch, the full record round-trips.
    reloaded = get_by_id(db_session, record.id)
    assert reloaded.status == DecisionStatus.APPROVED.value
    assert reloaded.observed_outcome is not None


def test_observe_outcome_refuses_a_decision_that_was_never_approved(db_session):
    record = decision_service.propose_decision(
        db_session,
        decision_type="aisle_stow_priority",
        context={"trigger": "test"},
        evidence=_EVIDENCE,
        scenario_path=_SCENARIO_PATH,
        candidates=_CANDIDATES,
        eval_seeds=_FAST_SEEDS,
    )

    with pytest.raises(ValueError):
        decision_service.observe_outcome(
            db_session, record, scenario_path=_SCENARIO_PATH, observe_seeds=_FAST_SEEDS
        )
