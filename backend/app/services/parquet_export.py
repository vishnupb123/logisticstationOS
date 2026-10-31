"""Export the event log of record to Parquet (ADR-0003): the durable,
portable intermediate between PostgreSQL (operational truth) and DuckDB
(local analytics) — see docs/DATA_ARCHITECTURE.md.

Deliberately exports only the `events` table, nothing from app/domain.
Every Milestone 3 metric (WIPS, induct throughput, jackpot volume, dwell
time, stow throughput) is derivable from the event log alone — exporting
the projected current-state tables too would duplicate data that's a
pure function of what's already here, for no analytical gain.
"""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.models import Event
from app.events.parquet_io import ExportResult, write_event_records_to_parquet


def export_events_to_parquet(session: Session, out_path: Path) -> ExportResult:
    rows = session.execute(select(Event).order_by(Event.occurred_at.asc())).scalars().all()

    records = [
        {
            "event_id": str(row.event_id),
            "event_type": row.event_type,
            "entity_type": row.entity_type,
            "entity_id": str(row.entity_id),
            "correlation_id": row.correlation_id,
            "occurred_at": row.occurred_at,
            "recorded_at": row.recorded_at,
            "source": row.source,
            "source_kind": row.source_kind,
            "provenance": row.provenance,
            "idempotency_key": row.idempotency_key,
            "schema_version": row.schema_version,
            "payload": json.dumps(row.payload),
        }
        for row in rows
    ]

    return write_event_records_to_parquet(records, out_path)
