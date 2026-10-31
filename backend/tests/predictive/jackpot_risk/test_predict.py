import joblib
import pandas as pd
import pytest

from app.predictive.jackpot_risk.dataset import FEATURE_COLUMNS
from app.predictive.jackpot_risk.model import LogisticRegressionRiskModel
from app.predictive.jackpot_risk.predict import load_model, predict, save_model


def _fitted_model() -> LogisticRegressionRiskModel:
    X = pd.DataFrame(
        {
            "mean_hamper_occupancy": [0.1, 0.9, 0.2, 0.8],
            "max_hamper_occupancy": [0.1, 0.9, 0.2, 0.8],
            "stower_utilization": [0.1, 0.9, 0.2, 0.8],
            "current_backlog": [0, 5, 0, 5],
        }
    )
    y = pd.Series([0, 1, 0, 1])
    return LogisticRegressionRiskModel().fit(X, y)


def test_save_and_load_model_round_trips(tmp_path):
    model = _fitted_model()
    path = tmp_path / "model.joblib"

    save_model(model, path, horizon_seconds=300.0)
    payload = load_model(path)

    assert payload["feature_columns"] == FEATURE_COLUMNS
    assert payload["horizon_seconds"] == 300.0
    assert "model_version" in payload


def test_load_model_rejects_a_stale_feature_schema(tmp_path):
    path = tmp_path / "stale_model.joblib"
    joblib.dump(
        {
            "model": _fitted_model(),
            "model_version": "old",
            "feature_columns": ["some", "old", "columns"],
            "horizon_seconds": 60.0,
        },
        path,
    )

    with pytest.raises(ValueError, match="retrain"):
        load_model(path)


def test_predict_matches_the_underlying_model_directly(tmp_path):
    model = _fitted_model()
    path = tmp_path / "model.joblib"
    save_model(model, path, horizon_seconds=300.0)
    payload = load_model(path)

    features = {
        "mean_hamper_occupancy": 0.9,
        "max_hamper_occupancy": 0.9,
        "stower_utilization": 0.9,
        "current_backlog": 5,
    }
    prediction = predict(payload, features)

    expected = model.predict_proba(pd.DataFrame([features]))[0]
    assert prediction.probability == pytest.approx(expected)
    assert prediction.horizon_seconds == 300.0
    assert prediction.features_used == features
