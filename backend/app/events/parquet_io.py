"""Shared Parquet writer for anything shaped like an events-table row —
used by the PostgreSQL export (app/services/parquet_export.py, Milestone
3) and by the digital twin's simulated event output (app/simulation,
Milestone 4), so both produce byte-for-byte the same schema and the dbt
project (backend/analytics/) can read either without caring which
produced it.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# payload is JSON in the source (Postgres JSONB, or a plain dict on a
# simulated EventEnvelope); Parquet has no native JSON type, so it's
# serialized to a JSON *string* column here — dbt/DuckDB models parse it
# back out with DuckDB's own JSON functions (json_extract_string, ->>).
COLUMNS = (
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


@dataclass(frozen=True)
class ExportResult:
    row_count: int
    out_path: Path


def write_event_records_to_parquet(records: list[dict], out_path: Path) -> ExportResult:
    """records: plain dicts with exactly COLUMNS' keys, payload already
    JSON-serialized to a string, occurred_at/recorded_at as datetimes.
    """
    frame = pd.DataFrame.from_records(records, columns=COLUMNS)
    # Explicit dtypes even for an empty frame, so an empty source still
    # produces a schema-valid (if zero-row) Parquet file rather than one
    # dbt's read_parquet can't infer columns from.
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
