"""Shared evidence types for every agent (docs/AGENTIC_ARCHITECTURE.md
§"Evidence provenance"). An agent cannot emit a bare string claim — it
emits a structured Finding with a category, supporting evidence
references, and (for predictions/recommendations) a confidence or
uncertainty indicator. The Orchestrator's future job when assembling a
multi-agent answer is to preserve these distinctions, not flatten them.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class EvidenceCategory(StrEnum):
    OBSERVATION = "observation"
    CALCULATED = "calculated"
    INFERRED = "inferred"
    HYPOTHESIS = "hypothesis"
    PREDICTION = "prediction"
    RECOMMENDATION = "recommendation"


class Finding(BaseModel):
    category: EvidenceCategory
    summary: str
    supporting_evidence: list[str] = Field(default_factory=list)
    confidence: float | None = None
    alternative_explanations: list[str] = Field(default_factory=list)
