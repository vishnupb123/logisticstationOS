#!/usr/bin/env python3
"""Export the PostgreSQL event log to a Parquet file dbt/DuckDB can read.

Example:
    python scripts/export_events_to_parquet.py --out ../data/processed/events.parquet

Run from backend/ with the `analytics` extra installed
(`pip install -e ".[dev,analytics]"`) and a reachable PostgreSQL.
"""

import argparse
from pathlib import Path

from app.db.postgres import SessionLocal
from app.services.parquet_export import export_events_to_parquet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="../data/processed/events.parquet",
        help="output Parquet file path (default: ../data/processed/events.parquet)",
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        result = export_events_to_parquet(session, Path(args.out))
    finally:
        session.close()

    print(f"exported {result.row_count} event(s) to {result.out_path}")


if __name__ == "__main__":
    main()
