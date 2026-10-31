"""Model persistence and inference-time interface for the jackpot-
accumulation-risk model (Milestone 8). A saved file is a plain dict
(not a bare sklearn object) so the version and feature list travel
with the model — a prediction can always be traced back to exactly
what produced it, per `docs/RL_ENVIRONMENT_SPEC.md`'s own precedent
of never letting a result be cited without its provenance.
"""

from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from app.predictive.jackpot_risk.dataset import FEATURE_COLUMNS
from app.predictive.jackpot_risk.model import MODEL_VERSION
from app.predictive.jackpot_risk.schemas import JackpotRiskPrediction


def save_model(model, path: str | Path, *, horizon_seconds: float) -> None:
    payload: dict[str, Any] = {
        "model": model,
        "model_version": MODEL_VERSION,
        "feature_columns": FEATURE_COLUMNS,
        "horizon_seconds": horizon_seconds,
    }
    joblib.dump(payload, path)


def load_model(path: str | Path) -> dict:
    payload = joblib.load(path)
    if payload.get("feature_columns") != FEATURE_COLUMNS:
        raise ValueError(
            f"model at {path} was trained with feature columns "
            f"{payload.get('feature_columns')}, which no longer matches "
            f"the current FEATURE_COLUMNS {FEATURE_COLUMNS} — retrain it"
        )
    return payload


def predict(payload: dict, features: dict[str, float]) -> JackpotRiskPrediction:
    row = pd.DataFrame([{col: features[col] for col in payload["feature_columns"]}])
    probability = float(payload["model"].predict_proba(row)[0])
    return JackpotRiskPrediction(
        probability=probability,
        horizon_seconds=payload["horizon_seconds"],
        model_version=payload["model_version"],
        features_used=dict(features),
    )
