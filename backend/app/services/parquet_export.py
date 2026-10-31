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
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.models import Event


@dataclass(frozen=True)
class ExportResult:
    row_count: int
    out_path: Path


# payload is JSONB in Postgres; Parquet has no native JSON type, so it's
# serialized to a JSON *string* column here — dbt/DuckDB models parse it
# back out with DuckDB's own JSON functions (json_extract_string, ->>).
_COLUMNS = (
    "event_id",
    "event_type",
    "entity_type",
    "entity_id",
    "correlation_id",
    "occurred_at",
    "recorded_at",
    "source",
    "source_kind",
    "provenance",
    "idempotency_key",
    "schema_version",
    "payload",
)


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

    frame = pd.DataFrame.from_records(records, columns=_COLUMNS)
    # Explicit dtypes even for an empty frame, so a from-scratch database
    # still produces a schema-valid (if zero-row) Parquet file rather than
    # one dbt's read_parquet can't infer columns from.
    frame = frame.astype(
        {
            "event_id": "string",
            "event_type": "string",
            "entity_type": "string",
            "entity_id": "string",
            "correlation_id": "string",
            "source": "string",
            "source_kind": "string",
            "provenance": "string",
            "idempotency_key": "string",
            "schema_version": "int64",
            "payload": "string",
        }
    )
    frame["occurred_at"] = pd.to_datetime(frame["occurred_at"], utc=True)
    frame["recorded_at"] = pd.to_datetime(frame["recorded_at"], utc=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out_path, engine="pyarrow", index=False)

    return ExportResult(row_count=len(frame), out_path=out_path)
