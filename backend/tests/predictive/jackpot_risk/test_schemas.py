from app.agents.schemas import EvidenceCategory
from app.predictive.jackpot_risk.schemas import JackpotRiskPrediction, to_finding


def test_to_finding_is_tagged_as_a_prediction_never_an_observation():
    prediction = JackpotRiskPrediction(
        probability=0.78,
        horizon_seconds=300.0,
        model_version="2026-10-31.1",
        features_used={"current_backlog": 3.0},
    )

    finding = to_finding(prediction)

    assert finding.category == EvidenceCategory.PREDICTION
    assert finding.category != EvidenceCategory.OBSERVATION
    assert "78%" in finding.summary
    assert "300" in finding.summary
    assert finding.supporting_evidence == ["jackpot_risk_model:2026-10-31.1"]


def test_to_finding_confidence_is_the_predicted_probability():
    prediction = JackpotRiskPrediction(
        probability=0.33,
        horizon_seconds=60.0,
        model_version="v1",
        features_used={},
    )

    finding = to_finding(prediction)

    assert finding.confidence == 0.33
