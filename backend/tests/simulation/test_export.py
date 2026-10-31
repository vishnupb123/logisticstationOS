import json

import pandas as pd

from app.events.parquet_io import COLUMNS
from app.simulation.config import ScenarioConfig
from app.simulation.export import write_run_manifest, write_simulation_result
from app.simulation.model import run_scenario


def _small_config() -> ScenarioConfig:
    return ScenarioConfig.model_validate(
        {
            "name": "export-test",
            "seed": 7,
            "station_layout": {
                "cluster_a_aisle_count": 2,
                "cluster_b_aisle_count": 0,
                "hamper_capacity": 2,
            },
            "truck_arrivals": {"truck_count": 1, "arrival_interval_minutes": 5},
            "parcels": {"parcels_per_truck": 5},
            "resources": {"induct_capacity": 1, "stower_count": 1},
        }
    )


def test_parquet_round_trips_with_the_same_schema_as_the_postgres_export(tmp_path):
    result = run_scenario(_small_config())

    out_path = tmp_path / "simulated_events.parquet"
    export_result = write_simulation_result(result, out_path)

    assert export_result.row_count == len(result.events)
    assert out_path.exists()

    frame = pd.read_parquet(out_path)
    assert list(frame.columns) == list(COLUMNS)
    assert len(frame) == len(result.events)

    sort_attempted_row = frame[frame["event_type"] == "parcel.sort_attempted"].iloc[0]
    payload = json.loads(sort_attempted_row["payload"])
    assert "outcome" in payload

    # Simulated data: no real ingestion delay to model, so recorded_at
    # is defined as equal to occurred_at (app/simulation/export.py).
    assert (frame["occurred_at"] == frame["recorded_at"]).all()
    assert frame["source_kind"].eq("simulated").all()


def test_run_manifest_records_reproducibility_metadata(tmp_path):
    result = run_scenario(_small_config())
    manifest_path = write_run_manifest(result, tmp_path / "run.manifest.json")

    manifest = json.loads(manifest_path.read_text())
    assert manifest["scenario_name"] == "export-test"
    assert manifest["seed"] == 7
    assert manifest["event_count"] == len(result.events)
    assert manifest["simpy_version"]
    assert manifest["run_id"]
