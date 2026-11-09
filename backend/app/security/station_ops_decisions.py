"""Governance pathway for Station Operations Agent recommendations
(decision_type ``station_ops_mitigation``) — the same DecisionRecord,
state machine, RBAC check and audit trail as aisle_stow_priority
(app/security/repository.py), so an agent recommendation can only become
"acted on" through approve_decision -> record_observed_outcome.

"Observed outcome" re-runs the station twin with the approved plan on
*fresh* seeds (never the seed used to justify it) and records the
simulated deltas — a simulated outcome, never a claim about a real site.
"""

from sqlalchemy.orm import Session

from app.agents.schemas import EvidenceCategory, Finding
from app.agents.station_ops.counterfactual import SCORE_VERSION, SCORE_WEIGHTS, evaluate
from app.agents.station_ops.mitigations import Candidate
from app.security import policy_engine, repository, risk
from app.security.models import DecisionRecord
from app.simulation.station_ops.model import Intervention
from app.simulation.station_ops.plan import build_preset

DECISION_TYPE = "station_ops_mitigation"
DEFAULT_OBSERVE_SEEDS = [301, 302, 303]


def propose_from_action(
    session: Session, *, action: dict, preset: str, seed: int, agent_execution_id: str | None
) -> DecisionRecord:
    """`action` is a serialized app/agents/station_ops/loop.py::AgentAction
    with evaluations. Candidates are its evaluated plans; nothing is
    approved here — the record is PENDING_APPROVAL by construction."""
    evaluations = action.get("evaluations") or []
    if not evaluations:
        raise ValueError("action has no evaluated candidates to propose")
    candidates = [
        {
            "name": e["name"],
            "description": (
                f"Simulated: DEA {e['delta_dea_pp']:+.2f}pp, OTD {e['delta_otd_pp']:+.2f}pp, "
                f"timely staged {e['delta_timely_staged_pp']:+.2f}pp, "
                f"{e['labor_hours']:.1f} labor h, score {e['score']}"
            ),
            "interventions": e["interventions"],
            "evaluation": {
                "outcome": e["outcome"],
                "score": e["score"],
                "delta_dea_pp": e["delta_dea_pp"],
                "delta_otd_pp": e["delta_otd_pp"],
                "delta_timely_staged_pp": e["delta_timely_staged_pp"],
                "labor_hours": e["labor_hours"],
            },
        }
        for e in evaluations
    ]
    policy = policy_engine.evaluate_station_ops(candidates)
    r = action["risk"]
    evidence = [
        Finding(
            category=EvidenceCategory(r["category"]),
            summary=r["summary"],
            supporting_evidence=[f"risk:{r['risk_type']}"],
        ),
        Finding(
            category=EvidenceCategory.CALCULATED,
            summary="Counterfactual comparison vs. baseline at "
            f"{action['clock']}: "
            + "; ".join(f"{e['name']} score {e['score']}" for e in evaluations[:5]),
            supporting_evidence=[f"candidate:{e['name']}" for e in evaluations[:5]],
        ),
    ]
    if action.get("chosen") and policy.eligible:
        evidence.append(
            Finding(
                category=EvidenceCategory.RECOMMENDATION,
                summary=f"Recommend '{action['chosen']}'. {action['rationale']} Simulated evidence "
                "only — requires approval (ADR-0009).",
                supporting_evidence=[f"candidate:{action['chosen']}"],
            )
        )
    return repository.create_decision_record(
        session,
        decision_type=DECISION_TYPE,
        context={
            "preset": preset,
            "seed": seed,
            "risk_type": r["risk_type"],
            "detected_at": action["clock"],
            "detected_at_minute": action["minute"],
            "agent_execution_id": agent_execution_id,
            "source": "station_ops_agent",
        },
        evidence=[f.model_dump(mode="json") for f in evidence],
        candidates=candidates,
        policy_engine_result=policy.model_dump(mode="json"),
        risk_evaluation=risk.evaluate_risk(DECISION_TYPE).model_dump(mode="json"),
        component_versions={
            "policy_engine": policy_engine.POLICY_VERSION,
            "station_ops_score": SCORE_VERSION,
        },
    )


def observe_outcome(
    session: Session, record: DecisionRecord, *, observe_seeds: list[int] | None = None
) -> DecisionRecord:
    if record.status != "approved":
        # repository.record_observed_outcome enforces this too; failing
        # early avoids running simulations for a decision that can't use them.
        raise ValueError(f"decision {record.id} is {record.status!r}, not approved")
    selected = next((c for c in record.candidates if c["name"] == record.selected_candidate), None)
    if selected is None:
        raise ValueError(f"decision {record.id} has no candidate {record.selected_candidate!r}")
    ivs = [Intervention.model_validate(iv) for iv in selected["interventions"]]
    per_seed = []
    for seed in observe_seeds or DEFAULT_OBSERVE_SEEDS:
        cfg = build_preset(record.context["preset"], seed)
        baseline, [ev] = evaluate(
            cfg,
            [],
            [
                Candidate(
                    name=selected["name"],
                    interventions=ivs,
                    labor_hours=selected["evaluation"]["labor_hours"],
                )
            ],
            try_combination=False,
        )
        per_seed.append(
            {
                "seed": seed,
                "baseline": baseline.model_dump(),
                "with_plan": ev.outcome.model_dump(),
                "delta_dea_pp": ev.delta_dea_pp,
                "delta_otd_pp": ev.delta_otd_pp,
                "delta_timely_staged_pp": ev.delta_timely_staged_pp,
                "score": ev.score,
            }
        )
    n = len(per_seed)
    outcome = {
        "kind": "simulated_rerun_on_fresh_seeds",
        "candidate": selected["name"],
        "score_weights": SCORE_WEIGHTS,
        "episodes": per_seed,
        "aggregate": {
            "mean_delta_dea_pp": round(sum(p["delta_dea_pp"] for p in per_seed) / n, 3),
            "mean_delta_otd_pp": round(sum(p["delta_otd_pp"] for p in per_seed) / n, 3),
            "mean_delta_timely_staged_pp": round(
                sum(p["delta_timely_staged_pp"] for p in per_seed) / n, 3
            ),
            "mean_score": round(sum(p["score"] for p in per_seed) / n, 3),
        },
    }
    return repository.record_observed_outcome(session, record, outcome)
