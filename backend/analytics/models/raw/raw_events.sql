-- Raw layer: a thin, literal read of the Parquet export
-- (backend/scripts/export_events_to_parquet.py). No transformation here
-- — if this doesn't match the exported file 1:1, every layer above it
-- is suspect, not just this one.
select *
from read_parquet('{{ var("events_parquet_path") }}')
