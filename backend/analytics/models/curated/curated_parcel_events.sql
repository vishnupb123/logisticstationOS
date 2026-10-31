-- One row per parcel-related event, with the payload fields each event
-- type actually carries pulled into typed columns. Scoped to only the
-- fields Milestone 3's metrics need (classification, sort outcome,
-- aisle_code, bag_code, stower_code) — not a generic "flatten
-- everything" model with no analytical purpose behind it.
select
    event_id,
    entity_id as parcel_id,
    event_type,
    occurred_at,
    payload->>'classification' as classification,
    payload->>'outcome' as sort_outcome,
    payload->>'aisle_code' as aisle_code,
    payload->>'bag_code' as bag_code,
    payload->>'stower_code' as stower_code
from {{ ref('cleaned_events') }}
where entity_type = 'parcel'
