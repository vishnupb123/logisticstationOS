from pathlib import Path

import pytest
from pydantic import ValidationError

from app.simulation.config import ScenarioConfig, load_scenario

_SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "simulation" / "scenarios"


@pytest.mark.parametrize("filename", ["normal_operations.yaml", "delayed_inbound_trucks.yaml"])
def test_shipped_scenarios_load(filename):
    config = load_scenario(_SCENARIOS_DIR / filename)
    assert isinstance(config, ScenarioConfig)
    assert config.truck_arrivals.truck_count > 0
    assert config.parcels.parcels_per_truck > 0


def test_missing_required_field_is_rejected(tmp_path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("name: bad\nseed: 1\n")  # missing truck_arrivals/parcels

    with pytest.raises(ValidationError):
        load_scenario(bad_yaml)


def test_station_layout_and_resources_have_sensible_defaults():
    config = load_scenario(_SCENARIOS_DIR / "normal_operations.yaml")
    assert config.station_layout.hamper_capacity > 0
    assert config.resources.stower_count > 0
    assert config.resources.induct_capacity > 0
