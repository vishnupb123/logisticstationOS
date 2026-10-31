"""The RL policy-comparison view (Milestone 10). Evaluates the two
baseline policies (never the trained PPO policy — see
`app/schemas/rl.py` for why) against a shipped scenario, reusing
`app/rl/evaluation.py`'s exact evaluation code so this reports numbers
the same way `scripts/run_rl_evaluation.py` does.
"""

from fastapi import APIRouter, HTTPException

from app.rl.baselines import RuleBasedPolicy, StaticBaselinePolicy
from app.rl.env import StowBalancingEnv
from app.rl.evaluation import evaluate_policy
from app.schemas.rl import EvaluateRequest, EvaluateResponse
from app.simulation.config import load_scenario, resolve_shipped_scenario_path
from app.simulation.model import aisle_codes_for

router = APIRouter(prefix="/rl", tags=["rl"])

_POLICY_FACTORIES = {
    "static_baseline": StaticBaselinePolicy,
    "rule_based_baseline": RuleBasedPolicy,
}


@router.post("/evaluate", response_model=EvaluateResponse)
def evaluate(request: EvaluateRequest) -> EvaluateResponse:
    try:
        path = resolve_shipped_scenario_path(request.scenario)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    config = load_scenario(path)
    n_aisles = len(aisle_codes_for(config))
    env = StowBalancingEnv(config)

    results = {}
    for policy_name in request.policies:
        policy = _POLICY_FACTORIES[policy_name](n_aisles)
        results[policy_name] = evaluate_policy(env, policy, request.seeds)

    return EvaluateResponse(scenario=request.scenario, seeds=request.seeds, results=results)
