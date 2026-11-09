"""Two baselines and one trained model for jackpot-accumulation-risk
(Milestone 8), mirroring docs/RL_ENVIRONMENT_SPEC.md's own baseline-
comparison discipline: no claim rests on the trained model's metrics
alone without a baseline comparison actually having run.

- `BaseRatePredictor`: predicts the training set's observed positive
  rate for every row, regardless of features — the floor any model
  with real signal must clear.
- `CurrentBacklogHeuristic`: a one-line rule a human might write
  ("predict growth iff backlog is already nonzero") — not learned or
  tuned, the same role app/rl/baselines.py::RuleBasedPolicy plays for
  the RL environment.
- `build_model()`: a scaled logistic regression (the `predictive`
  extra — not a base dependency, same reasoning as the `rl` extra).
  Deliberately simple and interpretable given a modest synthetic
  dataset size, not a complex model chosen to chase accuracy.
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.predictive.jackpot_risk.dataset import FEATURE_COLUMNS

#: Dated, bumped deliberately on any change to features/training
#: procedure — carried into every JackpotRiskPrediction
#: (app/predictive/jackpot_risk/schemas.py) so a prediction is always
#: traceable to the exact model version that produced it.
MODEL_VERSION = "2026-10-31.1"


class BaseRatePredictor:
    def fit(self, X: pd.DataFrame, y: pd.Series) -> "BaseRatePredictor":
        self._p = float(y.mean())
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return np.full(len(X), self._p)


class CurrentBacklogHeuristic:
    def fit(self, X: pd.DataFrame, y: pd.Series) -> "CurrentBacklogHeuristic":
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return (X["current_backlog"] > 0).astype(float).to_numpy()


class LogisticRegressionRiskModel:
    """Wraps a scaled sklearn LogisticRegression so it exposes the same
    `fit(X, y)` / `predict_proba(X) -> 1D array of P(positive)`
    interface as the two baselines above — one evaluation loop
    (scripts/train_jackpot_risk_model.py) drives all three identically,
    the same reasoning app/rl/baselines.py's policies share SB3's
    `.predict()` shape.
    """

    def __init__(self):
        self._pipeline = Pipeline(
            [
                ("scale", StandardScaler()),
                ("clf", LogisticRegression(max_iter=1000)),
            ]
        )

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "LogisticRegressionRiskModel":
        self._pipeline.fit(X[FEATURE_COLUMNS], y)
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self._pipeline.predict_proba(X[FEATURE_COLUMNS])[:, 1]

    @property
    def coefficients(self) -> dict[str, float]:
        """Interpretability — why this model was chosen over a more
        opaque one for a first attempt at this problem."""
        return dict(zip(FEATURE_COLUMNS, self._pipeline.named_steps["clf"].coef_[0], strict=True))
