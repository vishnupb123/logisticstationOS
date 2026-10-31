"""API-facing request/response models for the RL policy-comparison
view (`backend/app/api/routes/rl.py`). `EvaluateRequest.scenario` is a
shipped-scenario filename, not a filesystem path (same boundary as
`app/schemas/simulation.py`). Only the two baseline policies are
exposed here, not the trained PPO policy — there is no safe, generic
way to accept an arbitrary model file path from an HTTP caller, and
Milestone 6/7's own honest finding is that PPO isn't demonstrably
better anyway; a future, deliberately-scoped addition could let a
caller reference a named, server-side-registered model file if that's
ever needed.
"""

from typing import Literal

from pydantic import BaseModel, Field

PolicyName = Literal["static_baseline", "rule_based_baseline"]


class EvaluateRequest(BaseModel):
    scenario: str
    seeds: list[int] = Field(default=[101, 102, 103], min_length=1, max_length=20)
    policies: list[PolicyName] = Field(
        default=["static_baseline", "rule_based_baseline"], min_length=1
    )


class EvaluateResponse(BaseModel):
    scenario: str
    seeds: list[int]
    # policy name -> {"episodes": [...], "aggregate": {...}}, the same
    # shape app/rl/evaluation.py::evaluate_policy already returns.
    results: dict[str, dict]
    source_kind: str = "simulated"
