import pytest

from app.predictive.jackpot_risk.evaluation import evaluate_predictions


def test_perfect_predictions_score_perfectly():
    y_true = [0, 1, 0, 1]
    y_pred_proba = [0.0, 1.0, 0.0, 1.0]

    metrics = evaluate_predictions(y_true, y_pred_proba)

    assert metrics["accuracy"] == 1.0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 1.0
    assert metrics["roc_auc"] == 1.0


def test_positive_rate_reflects_the_true_labels_not_the_predictions():
    y_true = [1, 1, 1, 0]
    y_pred_proba = [0.0, 0.0, 0.0, 0.0]

    metrics = evaluate_predictions(y_true, y_pred_proba)

    assert metrics["positive_rate"] == 0.75


def test_single_class_y_true_gives_none_roc_auc_not_a_crash():
    y_true = [1, 1, 1, 1]
    y_pred_proba = [0.9, 0.1, 0.5, 0.8]

    metrics = evaluate_predictions(y_true, y_pred_proba)

    assert metrics["roc_auc"] is None
    assert metrics["accuracy"] is not None


def test_threshold_controls_the_decision_boundary():
    y_true = [0, 0, 1]
    y_pred_proba = [0.4, 0.4, 0.4]

    low_threshold = evaluate_predictions(y_true, y_pred_proba, threshold=0.3)  # predicts [1,1,1]
    high_threshold = evaluate_predictions(y_true, y_pred_proba, threshold=0.5)  # predicts [0,0,0]

    assert low_threshold["accuracy"] == pytest.approx(1 / 3)
    assert high_threshold["accuracy"] == pytest.approx(2 / 3)
