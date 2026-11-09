"""Evaluation metrics shared by every baseline and the trained model
(Milestone 8) — one implementation, so a baseline and the real model
are scored identically, the same reasoning app/rl/evaluation.py
applies to RL policy comparison.
"""

from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score


def evaluate_predictions(y_true, y_pred_proba, *, threshold: float = 0.5) -> dict:
    y_pred = [1 if p >= threshold else 0 for p in y_pred_proba]
    metrics = {
        "n": len(y_true),
        "positive_rate": sum(y_true) / len(y_true) if len(y_true) else 0.0,
        "accuracy": accuracy_score(y_true, y_pred),
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
    }
    # roc_auc_score is undefined with only one class present in y_true —
    # an honest None, not a crash or a fabricated number.
    metrics["roc_auc"] = roc_auc_score(y_true, y_pred_proba) if len(set(y_true)) > 1 else None
    return metrics
