# Importing every model module registers its table on Base.metadata
# (app.db.postgres.Base) — required for both Alembic autogenerate and
# Base.metadata.create_all(...) in tests to see these tables.
from app.domain import aisle, bag, parcel, station, stower, truck  # noqa: F401
