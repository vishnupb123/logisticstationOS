#!/usr/bin/env python3
"""Run a digital-twin scenario and write its output as Parquet + a run
manifest (docs/DIGITAL_TWIN_SPEC.md §Reproducibility).

Example:
    python scripts/run_simulation.py --scenario ../simulation/scenarios/normal_operations.yaml \
        --out ../data/processed/simulated_events.parquet

No database involved — the digital twin never touches PostgreSQL (see
app/simulation/model.py's module docstring for why).
"""

import argparse
from pathlib import Path

from app.simulation.config import load_scenario
from app.simulation.export import write_run_manifest, write_simulation_result
from app.simulation.model import run_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, help="path to a scenario YAML file")
    parser.add_argument(
        "--out",
        default="../data/processed/simulated_events.parquet",
        help="output Parquet file path",
    )
    args = parser.parse_args()

    config = load_scenario(args.scenario)
    result = run_scenario(config)

    out_path = Path(args.out)
    export_result = write_simulation_result(result, out_path)
    manifest_path = write_run_manifest(result, out_path.with_suffix(".manifest.json"))

    print(f"scenario '{config.name}' (seed={config.seed}): {export_result.row_count} event(s)")
    print(f"wrote {export_result.out_path}")
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()
