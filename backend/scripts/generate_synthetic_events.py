#!/usr/bin/env python3
"""Generate a reproducible synthetic Cycle-1 event stream.

Examples:
    python scripts/generate_synthetic_events.py --seed 42 --out ../data/synthetic/cycle1_seed42.json
    python scripts/generate_synthetic_events.py --seed 42 --seed-db   # also ingest into PostgreSQL

Run from backend/ with the package installed (`pip install -e ".[dev]"`) so
`import app...` resolves without path hacks.
"""

import argparse
import json
from pathlib import Path

from app.db.postgres import SessionLocal
from app.events.event_types import TRUCK_ARRIVED
from app.services.event_ingestion import ingest_event
from app.services.seed import seed_aisles, seed_station
from app.services.synthetic_events import SyntheticScenario, generate_cycle1_events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--trucks", type=int, default=5)
    parser.add_argument("--parcels-per-truck", type=int, default=20)
    parser.add_argument("--station-code", default="NOVA-1")
    parser.add_argument(
        "--out", default=None, help="write the generated events as JSON to this path"
    )
    parser.add_argument(
        "--seed-db", action="store_true", help="also ingest the events into PostgreSQL"
    )
    args = parser.parse_args()

    scenario = SyntheticScenario(
        seed=args.seed, truck_count=args.trucks, parcels_per_truck=args.parcels_per_truck
    )
    events = generate_cycle1_events(scenario)
    print(
        f"generated {len(events)} events for {args.trucks} truck(s) "
        f"x {args.parcels_per_truck} parcels"
    )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps([e.model_dump(mode="json") for e in events], indent=2))
        print(f"wrote {out_path}")

    if args.seed_db:
        session = SessionLocal()
        try:
            station = seed_station(session, code=args.station_code)
            seed_aisles(session, station)
            session.commit()

            appended = duplicates = 0
            for envelope in events:
                station_id = station.id if envelope.event_type == TRUCK_ARRIVED else None
                result = ingest_event(session, envelope, station_id=station_id)
                if result.status == "appended":
                    appended += 1
                else:
                    duplicates += 1
            session.commit()
            print(f"ingested into Postgres: {appended} appended, {duplicates} duplicate(s) skipped")
        finally:
            session.close()


if __name__ == "__main__":
    main()
