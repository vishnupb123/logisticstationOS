#!/usr/bin/env python3
"""The daily truckfile job: create the OFD date's (synthetic) truckfile if
it doesn't exist yet, then check every ferry-borne trip's sailing against
the ferry-status provider and write revised ETAs back.

Run it on a schedule (e.g. every 30 min through the night) so the
Command Center and the Station Operations Agent plan against current ETAs:

    # crontab: every 30 minutes, for tomorrow's OFD date
    */30 * * * * cd /path/to/StationOS/backend && \
        .venv/bin/python scripts/refresh_truckfile.py --date "$(date -v+1d +%F)"

Ferry statuses come from the seeded SyntheticFerryStatusProvider — a real
operator feed would be a FerryStatusProvider adapter (app/inbound/ferry.py),
deliberately not built in this synthetic-data repository.

Example:
    python scripts/refresh_truckfile.py --date 2026-11-09 --weather rough
"""

import argparse
import json
from datetime import date

from app.db.postgres import SessionLocal
from app.inbound import service
from app.inbound.ferry import SyntheticFerryStatusProvider


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", required=True, type=date.fromisoformat, help="OFD date")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--weather", choices=["calm", "rough", "severe"], default=None)
    args = parser.parse_args()

    with SessionLocal() as session:
        service.ensure_truckfile(session, args.date, seed=args.seed)
        summary = service.refresh_ferry_status(
            session,
            args.date,
            SyntheticFerryStatusProvider(seed=args.seed, force_weather=args.weather),
        )
        session.commit()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
