"""API-facing request/response models for the decision-governance
pipeline (`backend/app/api/routes/decisions.py`). Distinct from the
internal Pydantic models in `app/security/` (`CandidateIntervention`,
`PolicyEngineResult`, `RiskEvaluation`), which represent the
governance pipeline's own internal shapes — these are specifically
what an HTTP caller may send and what this API returns, per
`docs/SYSTEM_ARCHITECTURE.md`'s own note that `app/schemas/` would be
populated "once API-facing schemas are needed."

`ProposeDecisionRequest.scenario` is a shipped-scenario *filename*,
not a filesystem path — the route resolves it via
`app/simulation/config.py::resolve_shipped_scenario_path`, the same
path-traversal boundary every other Milestone 10 route observes.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.agents.schemas import Finding
from app.security.policy_engine import CandidateIntervention
from app.security.rbac import Role


class DecisionRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    decision_type: str
    status: str
    context: dict
    evidence: list[dict]
    candidates: list[dict]
    policy_engine_result: dict
    risk_evaluation: dict
    component_versions: dict
    selected_candidate: str | None
    approved_by: str | None
    approver_role: str | None
    approval_rationale: str | None
    decided_at: datetime | None
    observed_outcome: dict | None
    outcome_recorded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProposeDecisionRequest(BaseModel):
    decision_type: str
    context: dict
    evidence: list[Finding]
    scenario: str
    candidates: list[CandidateIntervention] = Field(min_length=1, max_length=10)
    eval_seeds: list[int] | None = Field(default=None, max_length=20)
    shadow: bool = False


class ApproveDecisionRequest(BaseModel):
    approved_by: str
    approver_role: Role
    selected_candidate: str
    rationale: str


class RejectDecisionRequest(BaseModel):
    approved_by: str
    approver_role: Role
    rationale: str


class ObserveOutcomeRequest(BaseModel):
    scenario: str
    observe_seeds: list[int] | None = Field(default=None, max_length=20)
