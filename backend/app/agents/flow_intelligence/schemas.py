from typing import Literal

from pydantic import BaseModel, Field

from app.agents.schemas import EvidenceCategory, Finding


class FlowIntelligenceInput(BaseModel):
    duckdb_path: str


class FlowIntelligenceOutput(BaseModel):
    findings: list[Finding]
    # Set when the LLM interpretation step never succeeded after retries
    # — the deterministic findings are still real and still returned;
    # this just says the interpretive layer on top of them is missing,
    # not fabricated to look complete.
    interpretation_error: str | None = None


class LLMFinding(BaseModel):
    """What the LLM is allowed to produce — structurally restricted to
    inferred/hypothesis/prediction. observation/calculated are reserved
    for the deterministic path (the LLM never computes a number the
    analytics layer should); recommendation is excluded because this
    agent's output doesn't go through Layer 5 approval
    (docs/ENGINEERING_ROADMAP.md Milestone 5 non-goal) — there is
    nothing for a recommendation here to be approved by yet.
    """

    category: Literal[
        EvidenceCategory.INFERRED, EvidenceCategory.HYPOTHESIS, EvidenceCategory.PREDICTION
    ]
    summary: str
    supporting_evidence: list[str] = Field(default_factory=list)
    confidence: float | None = None
    alternative_explanations: list[str] = Field(default_factory=list)


class LLMInterpretation(BaseModel):
    findings: list[LLMFinding]
