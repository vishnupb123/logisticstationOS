import pandas as pd
import pytest
from sklearn.exceptions import NotFittedError

from app.predictive.jackpot_risk.dataset import FEATURE_COLUMNS
from app.predictive.jackpot_risk.model import (
    BaseRatePredictor,
    CurrentBacklogHeuristic,
    LogisticRegressionRiskModel,
)


def _toy_frame(backlogs: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "mean_hamper_occupancy": [0.5] * len(backlogs),
            "max_hamper_occupancy": [0.5] * len(backlogs),
            "stower_utilization": [0.5] * len(backlogs),
            "current_backlog": backlogs,
        }
    )


def test_base_rate_predictor_returns_the_training_positive_rate_for_every_row():
    X = _toy_frame([0, 1, 2, 3])
    y = pd.Series([0, 1, 1, 1])

    model = BaseRatePredictor().fit(X, y)
    proba = model.predict_proba(X)

    assert (proba == 0.75).all()


def test_current_backlog_heuristic_ignores_fit_and_reacts_only_to_backlog():
    X = _toy_frame([0, 5, -1, 2])
    model = CurrentBacklogHeuristic().fit(X, pd.Series([0, 0, 0, 0]))

    proba = model.predict_proba(X)

    assert list(proba) == [0.0, 1.0, 0.0, 1.0]


def test_logistic_regression_learns_the_separable_toy_signal():
    # current_backlog > 0 perfectly predicts the label in this toy set —
    # a real model should learn the direction, not just memorize noise.
    backlogs = [0, 0, 0, 5, 5, 5, 10, 10, 10, 0]
    X = _toy_frame(backlogs)
    y = pd.Series([0, 0, 0, 1, 1, 1, 1, 1, 1, 0])

    model = LogisticRegressionRiskModel().fit(X, y)
    proba = model.predict_proba(X)

    assert proba[backlogs.index(10)] > proba[backlogs.index(0)]
    coefficients = model.coefficients
    assert set(coefficients) == set(FEATURE_COLUMNS)
    assert coefficients["current_backlog"] > 0


def test_logistic_regression_predict_proba_requires_fit_first():
    X = _toy_frame([0, 1])
    model = LogisticRegressionRiskModel()

    with pytest.raises(NotFittedError):
        model.predict_proba(X)
