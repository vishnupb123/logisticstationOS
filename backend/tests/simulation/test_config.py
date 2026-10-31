from pathlib import Path

import pytest
from pydantic import ValidationError

from app.simulation.config import (
    ScenarioConfig,
    list_shipped_scenarios,
    load_scenario,
    resolve_shipped_scenario_path,
)

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


def test_list_shipped_scenarios_includes_every_yaml_file():
    filenames = {s.filename for s in list_shipped_scenarios()}
    actual_files = {p.name for p in _SCENARIOS_DIR.glob("*.yaml")}
    assert filenames == actual_files
    assert "rl_stow_balancing.yaml" in filenames


def test_resolve_shipped_scenario_path_finds_a_real_file():
    path = resolve_shipped_scenario_path("normal_operations.yaml")
    assert path.is_file()
    assert path.parent == _SCENARIOS_DIR


def test_resolve_shipped_scenario_path_rejects_unknown_filenames():
    with pytest.raises(FileNotFoundError):
        resolve_shipped_scenario_path("does_not_exist.yaml")


def test_resolve_shipped_scenario_path_strips_directory_traversal():
    """An HTTP caller must never be able to turn this into an arbitrary
    filesystem read — Path(filename).name strips any directory
    component before the lookup, so a traversal attempt just fails to
    find a file named "passwd" inside the scenarios directory, rather
    than reading /etc/passwd.
    """
    with pytest.raises(FileNotFoundError):
        resolve_shipped_scenario_path("../../../../etc/passwd")
