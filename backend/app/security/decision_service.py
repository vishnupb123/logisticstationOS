"""Milestone 7's "controlled decision interface connecting the
agentic layer, the RL layer, and a policy engine"
(docs/ENGINEERING_ROADMAP.md). This is Layer 5 code (app/security/) by
design — it is the thing docs/SECURITY_AND_GOVERNANCE.md's governance
pipeline diagram describes end to end, so it is allowed to read
downward from Layer 4 (app/rl, app/simulation) and the shared Layer 4
evidence schema (app/agents/schemas.py::Finding), per
docs/SYSTEM_ARCHITECTURE.md's "layers depend downward only." It does
not import any specific agent module — the caller (a script, or a
future orchestrator) is responsible for turning an agent's output into
the `evidence` argument here, keeping this module decoupled from which
agent produced it.

Deliberately does NOT use the trained PPO policy from Milestone 6: the
honest finding there (docs/RL_ENVIRONMENT_SPEC.md) is that PPO's
reward advantage never translated into a better jackpot-backlog
outcome than the baselines — citing it as a candidate here would
overstate its value (docs/OPEN_QUESTIONS.md, "leaning: not yet"). The
coordination mechanism built here is independent of any one candidate
being especially good: it works the same way whether a candidate turns
out to help or not, which is the entire point.
"""

import uuid

from sqlalchemy.orm import Session

from app.agents.schemas import EvidenceCategory, Finding
from app.core.tracing import get_tracer
from app.rl.baselines import FixedWeightPolicy
from app.rl.env import DEFAULT_DECISION_INTERVAL_SECONDS, DEFAULT_MAX_STEPS, StowBalancingEnv
from app.rl.evaluation import evaluate_policy
from app.security import policy_engine, repository, risk
from app.security.models import DecisionRecord
from app.security.policy_engine import CandidateIntervention
from app.simulation.config import load_scenario
from app.simulation.model import aisle_codes_for

tracer = get_tracer(__name__)

#: Disjoint from scripts/run_rl_evaluation.py's _EVAL_SEEDS (101-105) —
#: a decision's own candidate evaluation and the Milestone 6 baseline
#: report are separate exercises that shouldn't be mistaken for reusing
#: each other's numbers.
DEFAULT_EVAL_SEEDS = [201, 202, 203, 204, 205]
#: Distinct again from DEFAULT_EVAL_SEEDS — "observed outcome" is a
#: fresh simulation run with the approved candidate's weights, not a
#: copy of the number that was already used to justify approving it.
DEFAULT_OBSERVE_SEEDS = [301, 302, 303, 304, 305]


def _weights_vector(candidate: CandidateIntervention, aisle_codes: list[str]) -> list[float]:
    missing = [code for code in aisle_codes if code not in candidate.priority_weights]
    if missing:
        raise ValueError(
            f"candidate {candidate.name!r} is missing priority_weights for aisles: {missing}"
        )
    return [candidate.priority_weights[code] for code in aisle_codes]


def evaluate_candidates(
    scenario_path: str,
    candidates: list[CandidateIntervention],
    *,
    eval_seeds: list[int] = DEFAULT_EVAL_SEEDS,
    decision_interval_seconds: float = DEFAULT_DECISION_INTERVAL_SECONDS,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> list[dict]:
    """Requests a simulation-based policy evaluation for each candidate
    — the "request a simulation... request policy evaluation" step of
    the roadmap's Milestone 7 deliverable. Reuses app/rl/evaluation.py,
    the same code path scripts/run_rl_evaluation.py uses for the
    baseline report, so a candidate's numbers are produced the same way
    a trained policy's would be.
    """
    config = load_scenario(scenario_path)
    aisle_codes = aisle_codes_for(config)
    env = StowBalancingEnv(
        config, decision_interval_seconds=decision_interval_seconds, max_steps=max_steps
    )

    results = []
    for candidate in candidates:
        weights = _weights_vector(candidate, aisle_codes)
        policy = FixedWeightPolicy(weights)
        evaluation = evaluate_policy(env, policy, eval_seeds)
        results.append(
            {
                "name": candidate.name,
                "description": candidate.description,
                "priority_weights": candidate.priority_weights,
                "evaluation": evaluation,
            }
        )
    return results


def _explain(
    candidate_results: list[dict], policy_result: policy_engine.PolicyEngineResult
) -> list[Finding]:
    """Deterministic "explain results": no LLM involved — these numbers
    came straight out of simulation, so interpreting them is a
    calculation, not an inference, and the one candidate highlighted is
    a recommendation (now meaningful for the first time, per
    app/agents/flow_intelligence/schemas.py's own note that it had
    "nothing for a recommendation here to be approved by yet" before
    Layer 5 existed) — never auto-applied, only ever proposed for
    approve_decision/reject_decision to act on.
    """
    comparison = ", ".join(
        f"{c['name']}: backlog={c['evaluation']['aggregate']['max_jackpot_backlog_mean']:.1f}"
        f" reward={c['evaluation']['aggregate']['total_reward_mean']:.1f}"
        for c in candidate_results
    )
    n_seeds = len(candidate_results[0]["evaluation"]["episodes"])
    findings = [
        Finding(
            category=EvidenceCategory.CALCULATED,
            summary=f"Simulated outcome per candidate across {n_seeds} seeds: {comparison}.",
            supporting_evidence=[f"candidate:{c['name']}" for c in candidate_results],
        )
    ]

    if not policy_result.eligible:
        return findings

    best = min(
        candidate_results,
        key=lambda c: c["evaluation"]["aggregate"]["max_jackpot_backlog_mean"],
    )
    findings.append(
        Finding(
            category=EvidenceCategory.RECOMMENDATION,
            summary=(
                f"Recommend candidate '{best['name']}' — lowest simulated mean jackpot "
                f"backlog ({best['evaluation']['aggregate']['max_jackpot_backlog_mean']:.1f}) "
                "among evaluated candidates. Requires explicit approval before being treated "
                "as adopted (ADR-0009) — simulated evidence only, not a live-operations result."
            ),
            supporting_evidence=[f"candidate:{best['name']}"],
        )
    )
    return findings


def propose_decision(
    session: Session,
    *,
    decision_type: str,
    context: dict,
    evidence: list[Finding],
    scenario_path: str,
    candidates: list[CandidateIntervention],
    eval_seeds: list[int] = DEFAULT_EVAL_SEEDS,
    shadow: bool = False,
) -> DecisionRecord:
    """The full "investigate -> formulate a decision problem -> request
    simulation/policy evaluation -> compare candidates -> explain
    results" pipeline, ending in a DecisionRecord that is always
    PENDING_APPROVAL (or SHADOW, if `shadow=True` — Milestone 9: a
    decision proposed to see what the pipeline *would* recommend,
    never eligible for approval, e.g. while trying out a new candidate
    shape before trusting it in the real approval queue) — nothing
    here can mark a decision approved.
    """
    with tracer.start_as_current_span(
        "decision.propose",
        attributes={
            "decision.type": decision_type,
            "decision.candidate_count": len(candidates),
            "decision.shadow": shadow,
        },
    ):
        candidate_results = evaluate_candidates(scenario_path, candidates, eval_seeds=eval_seeds)

        policy_result = policy_engine.evaluate(decision_type, candidates)
        risk_result = risk.evaluate_risk(decision_type)
        explanation = _explain(candidate_results, policy_result)

        return repository.create_decision_record(
            session,
            decision_type=decision_type,
            context=context,
            evidence=[f.model_dump(mode="json") for f in [*evidence, *explanation]],
            candidates=candidate_results,
            policy_engine_result=policy_result.model_dump(mode="json"),
            risk_evaluation=risk_result.model_dump(mode="json"),
            component_versions={"policy_engine": policy_engine.POLICY_VERSION},
            shadow=shadow,
        )


def observe_outcome(
    session: Session,
    record: DecisionRecord,
    *,
    scenario_path: str,
    observe_seeds: list[int] = DEFAULT_OBSERVE_SEEDS,
) -> DecisionRecord:
    """Runs a fresh simulation with the approved candidate's weights and
    records the result as the decision's observed outcome.
    record_observed_outcome (app/security/repository.py) refuses this
    unless `record` is already APPROVED — the structural guard that
    makes "no path lets a recommendation become acted on without
    approval" true, not just documented.
    """
    with tracer.start_as_current_span(
        "decision.observe_outcome", attributes={"decision.id": str(record.id)}
    ):
        selected = next(
            (c for c in record.candidates if c["name"] == record.selected_candidate), None
        )
        if selected is None:
            raise ValueError(
                f"decision {record.id} has no candidate matching selected_candidate "
                f"{record.selected_candidate!r}"
            )

        candidate = CandidateIntervention(
            name=selected["name"],
            description=selected["description"],
            priority_weights=selected["priority_weights"],
        )
        config = load_scenario(scenario_path)
        aisle_codes = aisle_codes_for(config)
        env = StowBalancingEnv(config)
        weights = _weights_vector(candidate, aisle_codes)
        outcome = evaluate_policy(env, FixedWeightPolicy(weights), observe_seeds)

        return repository.record_observed_outcome(session, record, outcome)


def get_decision(session: Session, decision_id: uuid.UUID) -> DecisionRecord | None:
    return repository.get_by_id(session, decision_id)
