from pathlib import Path

import pytest

from app.predictive.jackpot_risk.dataset import (
    ALL_COLUMNS,
    FEATURE_COLUMNS,
    DatasetSpec,
    build_dataset,
    run_episode_snapshots,
    temporal_train_test_split,
)
from app.simulation.config import load_scenario

_SCENARIO_PATH = str(
    Path(__file__).resolve().parents[4] / "simulation" / "scenarios" / "rl_stow_balancing.yaml"
)


def test_feature_columns_excludes_the_clock_proxy_columns():
    assert "trucks_remaining" not in FEATURE_COLUMNS
    assert "parcels_inducted" not in FEATURE_COLUMNS
    assert "trucks_remaining" in ALL_COLUMNS
    assert "parcels_inducted" in ALL_COLUMNS
    assert set(FEATURE_COLUMNS).issubset(set(ALL_COLUMNS))


def test_run_episode_snapshots_produces_binary_labels():
    config = load_scenario(_SCENARIO_PATH)
    rows = run_episode_snapshots(
        config, seed=1, decision_interval_seconds=60.0, horizon_seconds=300.0
    )

    assert len(rows) > 0
    for row in rows:
        assert row["label_backlog_grows"] in (0, 1)
        for col in ALL_COLUMNS:
            assert col in row


def test_run_episode_snapshots_is_deterministic():
    config = load_scenario(_SCENARIO_PATH)
    rows_a = run_episode_snapshots(
        config, seed=7, decision_interval_seconds=60.0, horizon_seconds=300.0
    )
    rows_b = run_episode_snapshots(
        config, seed=7, decision_interval_seconds=60.0, horizon_seconds=300.0
    )

    assert rows_a == rows_b


def test_tail_rows_without_a_future_horizon_are_dropped_not_fabricated():
    config = load_scenario(_SCENARIO_PATH)
    # An enormous horizon means no row can ever have a real future to
    # label against — the dataset must come back empty, not padded with
    # a placeholder label.
    rows = run_episode_snapshots(
        config, seed=1, decision_interval_seconds=60.0, horizon_seconds=1_000_000.0
    )
    assert rows == []


def test_build_dataset_concatenates_across_seeds():
    spec = DatasetSpec(scenario_path=_SCENARIO_PATH)
    df = build_dataset(spec, [1, 2])

    assert set(df["seed"].unique()) == {1, 2}
    assert len(df) > 0


def test_temporal_split_partitions_by_seed_with_no_overlap():
    spec = DatasetSpec(scenario_path=_SCENARIO_PATH)
    df = build_dataset(spec, [1, 2, 3, 4])

    train_df, test_df = temporal_train_test_split(df, [1, 2], [3, 4])

    assert set(train_df["seed"].unique()) == {1, 2}
    assert set(test_df["seed"].unique()) == {3, 4}
    assert len(train_df) + len(test_df) == len(df)


def test_temporal_split_rejects_overlapping_seeds():
    spec = DatasetSpec(scenario_path=_SCENARIO_PATH)
    df = build_dataset(spec, [1, 2])

    with pytest.raises(ValueError, match="disjoint"):
        temporal_train_test_split(df, [1, 2], [2, 3])
