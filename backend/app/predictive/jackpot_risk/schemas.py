"""Prediction output schema for the jackpot-accumulation-risk model
(Milestone 8). `to_finding` converts a prediction into the shared
evidence-category scheme (`app/agents/schemas.py`) — the `prediction`
category is exactly what `docs/AGENTIC_ARCHITECTURE.md` reserves for
this kind of output, carrying an explicit uncertainty indicator
(`confidence`), never presented as an `observation`.

This is deliberately NOT wired into the Flow Intelligence Agent or
app/security/decision_service.py this milestone — same reasoning
Milestone 6/7 gave for not wiring the trained RL policy into anything
beyond its own evaluation report: a first model's output shouldn't be
cited as agent/decision evidence before its own limitations (see
docs/PREDICTIVE_INTELLIGENCE_SPEC.md) have been read by whoever wires
it in next.
"""

from pydantic import BaseModel

from app.agents.schemas import EvidenceCategory, Finding


class JackpotRiskPrediction(BaseModel):
    probability: float
    horizon_seconds: float
    model_version: str
    features_used: dict[str, float]


def to_finding(prediction: JackpotRiskPrediction) -> Finding:
    return Finding(
        category=EvidenceCategory.PREDICTION,
        summary=(
            f"Estimated {prediction.probability:.0%} probability the jackpot backlog "
            f"grows within the next {prediction.horizon_seconds:.0f}s, based on current "
            "hamper occupancy, stower utilization, and backlog state."
        ),
        supporting_evidence=[f"jackpot_risk_model:{prediction.model_version}"],
        # The predicted probability itself IS the uncertainty indicator
        # this finding carries — not a separate, unrelated confidence.
        confidence=prediction.probability,
    )
