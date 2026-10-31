-- Metric contract: docs/OPERATIONAL_DOMAIN_MODEL.md §4.1 "Parcel dwell
-- time" — status: proposed. Defined here specifically as induct→stow
-- elapsed time, for stowed parcels only — dwell time for a parcel
-- still in flight, or diverted to an unmodeled exception workflow, isn't
-- a completed measurement yet.
select
    parcel_id,
    inducted_at,
    stowed_at,
    date_diff('second', inducted_at, stowed_at) as dwell_seconds
from {{ ref('curated_parcel_lifecycle') }}
where stowed_at is not null
