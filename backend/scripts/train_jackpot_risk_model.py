#!/usr/bin/env python3
"""Builds the jackpot-accumulation-risk dataset, splits it temporally
(by episode/seed, never by shuffling rows), trains the baselines and
the real model, evaluates all three on the held-out test episodes,
AND on two scenario variations never trained on (the same held-out-
scenario rigor docs/RL_ENVIRONMENT_SPEC.md applied to the RL policy
comparison), and writes an evaluation report
(docs/ENGINEERING_ROADMAP.md Milestone 8; docs/PREDICTIVE_INTELLIGENCE_SPEC.md).

Needs the `predictive` extra (pip install -e ".[dev,predictive]").

Example:
    python scripts/train_jackpot_risk_model.py \
        --scenario ../simulation/scenarios/rl_stow_balancing.yaml \
        --train-seeds 1-40 --test-seeds 41-60 \
        --model-out ../ml/models/jackpot_risk_model.joblib \
        --report-out ../data/processed/jackpot_risk_evaluation_report.json
"""

import argparse
import json
from pathlib import Path

from app.predictive.jackpot_risk.dataset import (
    FEATURE_COLUMNS,
    DatasetSpec,
    build_dataset,
    temporal_train_test_split,
)
from app.predictive.jackpot_risk.evaluation import evaluate_predictions
from app.predictive.jackpot_risk.model import (
    MODEL_VERSION,
    BaseRatePredictor,
    CurrentBacklogHeuristic,
    LogisticRegressionRiskModel,
)
from app.predictive.jackpot_risk.predict import save_model

#: Scenario variants never trained on — same purpose as
#: docs/RL_ENVIRONMENT_SPEC.md's held-out scenarios: does this
#: generalize, or only work against the exact world it was trained on.
_HELD_OUT_SCENARIOS = {
    "held_out_high_volume": "../simulation/scenarios/rl_stow_balancing_high_volume.yaml",
    "held_out_tighter_capacity": "../simulation/scenarios/rl_stow_balancing_tighter_capacity.yaml",
}
#: Disjoint from any --train-seeds/--test-seeds range a caller would
#: reasonably pass for the primary scenario.
_HELD_OUT_SCENARIO_SEEDS = list(range(201, 221))


def _parse_seed_range(spec: str) -> list[int]:
    """"1-40" -> [1..40]; also accepts a comma-separated list "1,2,3"."""
    if "-" in spec:
        start, end = spec.split("-")
        return list(range(int(start), int(end) + 1))
    return [int(s) for s in spec.split(",")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--train-seeds", required=True, help='e.g. "1-40"')
    parser.add_argument("--test-seeds", required=True, help='e.g. "41-60"')
    parser.add_argument("--decision-interval-seconds", type=float, default=60.0)
    parser.add_argument("--horizon-seconds", type=float, default=300.0)
    parser.add_argument("--model-out", required=True)
    parser.add_argument("--report-out", required=True)
    args = parser.parse_args()

    train_seeds = _parse_seed_range(args.train_seeds)
    test_seeds = _parse_seed_range(args.test_seeds)

    spec = DatasetSpec(
        scenario_path=args.scenario,
        decision_interval_seconds=args.decision_interval_seconds,
        horizon_seconds=args.horizon_seconds,
    )
    print(
        f"Building dataset: {len(train_seeds)} train episodes, "
        f"{len(test_seeds)} test episodes..."
    )
    df = build_dataset(spec, [*train_seeds, *test_seeds])
    train_df, test_df = temporal_train_test_split(df, train_seeds, test_seeds)
    print(f"Train rows: {len(train_df)}, test rows: {len(test_df)}")

    X_train, y_train = train_df[FEATURE_COLUMNS], train_df["label_backlog_grows"]
    X_test, y_test = test_df[FEATURE_COLUMNS], test_df["label_backlog_grows"]

    candidates = {
        "base_rate": BaseRatePredictor(),
        "current_backlog_heuristic": CurrentBacklogHeuristic(),
        "logistic_regression": LogisticRegressionRiskModel(),
    }

    report: dict = {
        "model_version": MODEL_VERSION,
        "scenario": args.scenario,
        "train_seeds": train_seeds,
        "test_seeds": test_seeds,
        "decision_interval_seconds": args.decision_interval_seconds,
        "horizon_seconds": args.horizon_seconds,
        "feature_columns": FEATURE_COLUMNS,
        "candidates": {},
    }

    trained_model = None
    for name, candidate in candidates.items():
        candidate.fit(X_train, y_train)
        if name == "logistic_regression":
            trained_model = candidate
        train_metrics = evaluate_predictions(y_train.tolist(), candidate.predict_proba(X_train))
        test_metrics = evaluate_predictions(y_test.tolist(), candidate.predict_proba(X_test))
        report["candidates"][name] = {"train": train_metrics, "test": test_metrics}
        print(
            f"  {name}: test accuracy={test_metrics['accuracy']:.3f} "
            f"precision={test_metrics['precision']:.3f} recall={test_metrics['recall']:.3f} "
            f"roc_auc={test_metrics['roc_auc']}"
        )

    print("\nHeld-out scenario generalization (never trained on):")
    report["held_out_scenarios"] = {}
    for scenario_label, scenario_path in _HELD_OUT_SCENARIOS.items():
        held_out_spec = DatasetSpec(
            scenario_path=scenario_path,
            decision_interval_seconds=args.decision_interval_seconds,
            horizon_seconds=args.horizon_seconds,
        )
        held_out_df = build_dataset(held_out_spec, _HELD_OUT_SCENARIO_SEEDS)
        X_held_out = held_out_df[FEATURE_COLUMNS]
        y_held_out = held_out_df["label_backlog_grows"].tolist()

        scenario_report = {}
        for name, candidate in candidates.items():
            metrics = evaluate_predictions(y_held_out, candidate.predict_proba(X_held_out))
            scenario_report[name] = metrics
        report["held_out_scenarios"][scenario_label] = {
            "scenario_path": scenario_path,
            "seeds": _HELD_OUT_SCENARIO_SEEDS,
            "candidates": scenario_report,
        }
        lr_metrics = scenario_report["logistic_regression"]
        print(
            f"  {scenario_label}: logistic_regression accuracy={lr_metrics['accuracy']:.3f} "
            f"roc_auc={lr_metrics['roc_auc']}"
        )

    save_model(trained_model, args.model_out, horizon_seconds=args.horizon_seconds)
    print(f"\nsaved model to {args.model_out}")

    report_path = Path(args.report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
