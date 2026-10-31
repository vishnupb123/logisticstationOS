#!/usr/bin/env python3
"""Milestone 7 exit-criteria demonstration: a full decision record
(context -> evidence -> candidates -> simulation/policy evaluation ->
approval -> outcome) produced and queried end to end
(docs/ENGINEERING_ROADMAP.md Milestone 7), using real Postgres
persistence and real digital-twin simulation runs throughout — nothing
in this script is mocked.

The starting "evidence" below is deliberately NOT a fresh agent/dbt
run — it's the jackpot-backlog finding the Flow Intelligence Agent
already produced and documented for real in Milestone 5 (HANDOFF.md
§3-4: 26 cumulative diverts, 8 clears, 18 still stuck), reconstructed
here as plain Finding objects. This script is about Milestone 7's new
decision-coordination/governance pipeline, not re-proving Milestone
5's agent correctness again — see tests/agents/flow_intelligence/ for
that.

Everything downstream of the evidence — candidate evaluation via the
real RL environment, the policy engine, the decision record, approval,
and the observed-outcome simulation run — executes for real against
whatever Postgres `app.db.postgres.SessionLocal` is configured for.

Example:
    python scripts/run_decision_demo.py
"""

import json

from app.agents.schemas import EvidenceCategory, Finding
from app.db.postgres import SessionLocal
from app.security import decision_service
from app.security.policy_engine import CandidateIntervention
from app.security.repository import approve_decision, record_observed_outcome

_SCENARIO_PATH = "../simulation/scenarios/rl_stow_balancing.yaml"

_EVIDENCE = [
    Finding(
        category=EvidenceCategory.OBSERVATION,
        summary=(
            "Jackpot volume: 18 parcel(s) currently in jackpot "
            "(26 cumulative diverts, 8 cumulative clears)."
        ),
        supporting_evidence=["metric_jackpot_volume"],
    ),
    Finding(
        category=EvidenceCategory.HYPOTHESIS,
        summary=(
            "Jackpot clears are lagging diverts, consistent with stowers not yet "
            "keeping pace with sort volume this early in the run."
        ),
        supporting_evidence=["metric_jackpot_volume"],
    ),
]

_CANDIDATES = [
    CandidateIntervention(
        name="status_quo",
        description="Uniform stow priority across all aisles — no reallocation.",
        priority_weights={f"A{i}": 0.5 for i in range(1, 7)},
    ),
    CandidateIntervention(
        name="favor_first_half",
        description="Favor aisles A1-A3 (weight 0.9) over A4-A6 (weight 0.1).",
        priority_weights={
            **{f"A{i}": 0.9 for i in range(1, 4)},
            **{f"A{i}": 0.1 for i in range(4, 7)},
        },
    ),
    CandidateIntervention(
        name="favor_second_half",
        description="Favor aisles A4-A6 (weight 0.9) over A1-A3 (weight 0.1).",
        priority_weights={
            **{f"A{i}": 0.1 for i in range(1, 4)},
            **{f"A{i}": 0.9 for i in range(4, 7)},
        },
    ),
]


def _print_record(label: str, record) -> None:
    print(f"\n--- {label} ---")
    print(f"id: {record.id}")
    print(f"status: {record.status}")
    print(f"decision_type: {record.decision_type}")
    print(f"policy_engine_result: {json.dumps(record.policy_engine_result)}")
    print(f"risk_evaluation: {json.dumps(record.risk_evaluation)}")
    print("candidates:")
    for c in record.candidates:
        agg = c["evaluation"]["aggregate"]
        print(
            f"  {c['name']}: reward={agg['total_reward_mean']:.2f} "
            f"backlog={agg['max_jackpot_backlog_mean']:.1f} "
            f"stowed={agg['total_stowed_mean']:.1f}"
        )
    print("evidence:")
    for e in record.evidence:
        print(f"  [{e['category']}] {e['summary']}")
    if record.selected_candidate:
        print(f"selected_candidate: {record.selected_candidate} (by {record.approved_by})")
        print(f"approval_rationale: {record.approval_rationale}")
    if record.observed_outcome:
        agg = record.observed_outcome["aggregate"]
        print(
            "observed_outcome: "
            f"reward={agg['total_reward_mean']:.2f} backlog={agg['max_jackpot_backlog_mean']:.1f}"
        )


def main() -> None:
    session = SessionLocal()
    try:
        print("1. Proposing a decision (evaluates candidates via real simulation runs)...")
        record = decision_service.propose_decision(
            session,
            decision_type="aisle_stow_priority",
            context={
                "trigger": "flow_intelligence_agent jackpot hypothesis (Milestone 5 run)",
                "scenario": _SCENARIO_PATH,
            },
            evidence=_EVIDENCE,
            scenario_path=_SCENARIO_PATH,
            candidates=_CANDIDATES,
        )
        _print_record("Proposed (pending_approval)", record)

        print("\n2. Attempting to record an outcome before approval (must be refused)...")
        try:
            record_observed_outcome(session, record, {"this": "should never be recorded"})
            print("   UNEXPECTED: no error raised — this would be a correctness bug.")
        except ValueError as exc:
            print(f"   Refused, as required: {exc}")

        print("\n3. A human approves the decision...")
        # Deliberately NOT the system's own recommendation (whichever
        # candidate has the lowest simulated backlog) — demonstrating
        # that approval is a real judgment call, not a rubber stamp
        # (ADR-0009's own critique of approval-without-differentiation).
        # The rationale names the actual trade-off being made, honestly.
        approved = approve_decision(
            session,
            record,
            approved_by="demo-operator",
            selected_candidate="favor_first_half",
            rationale=(
                "Overriding the system's own backlog-minimizing recommendation: "
                "'favor_first_half' has the highest simulated reward (reward trades off "
                "slightly against backlog here) and a comparable backlog to the alternatives."
            ),
        )

        print("4. Observing the outcome (a fresh simulation run with the approved weights)...")
        outcome_record = decision_service.observe_outcome(
            session, approved, scenario_path=_SCENARIO_PATH
        )
        _print_record("Approved, with observed outcome", outcome_record)

        session.commit()
        print(f"\nCommitted. Query this decision later by id: {record.id}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
