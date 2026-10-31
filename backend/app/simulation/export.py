"""Write a SimulationResult to Parquet in exactly the same shape
PostgreSQL export produces (app/events/parquet_io.py), plus a run
manifest recording what produced it (docs/DIGITAL_TWIN_SPEC.md
§Reproducibility: scenario, seed, library version, run id).
"""

import json
from pathlib import Path

from app.events.parquet_io import ExportResult, write_event_records_to_parquet
from app.simulation.model import SimulationResult


def write_simulation_result(result: SimulationResult, out_path: Path) -> ExportResult:
    records = [
        {
            "event_id": str(e.event_id),
            "event_type": e.event_type,
            "entity_type": e.entity_type,
            "entity_id": str(e.entity_id),
            "correlation_id": e.correlation_id,
            "occurred_at": e.occurred_at,
            # Simulated data has no real ingestion delay to model — there
            # is no EventStore step, so recorded_at is defined as equal
            # to occurred_at rather than fabricating a fake one.
            "recorded_at": e.occurred_at,
            "source": e.source,
            "source_kind": e.source_kind.value,
            "provenance": e.provenance,
            "idempotency_key": e.resolved_idempotency_key(),
            "schema_version": e.schema_version,
            "payload": json.dumps(e.payload),
        }
        for e in result.events
    ]
    return write_event_records_to_parquet(records, out_path)


def write_run_manifest(result: SimulationResult, out_path: Path) -> Path:
    manifest = {
        "run_id": str(result.run_id),
        "scenario_name": result.scenario_name,
        "seed": result.seed,
        "simpy_version": result.simpy_version,
        "generated_at": result.generated_at.isoformat(),
        "event_count": len(result.events),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2))
    return out_path
