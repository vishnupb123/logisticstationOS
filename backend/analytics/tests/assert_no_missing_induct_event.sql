-- Referential integrity (docs/ENGINEERING_ROADMAP.md Milestone 3 test
-- category): every non-inducted parcel event's entity must also have a
-- parcel.inducted event. This is the dbt-layer check for the same
-- invariant backend/app/services/event_ingestion.py's projector flags
-- (lifecycle_consistent=False) at the application layer — reinforced
-- here, not duplicated for its own sake, because an analytics consumer
-- querying this warehouse directly has no way to see that application-
-- layer flag.
select distinct entity_id
from {{ ref('cleaned_events') }}
where entity_type = 'parcel'
  and event_type != 'parcel.inducted'
  and entity_id not in (
      select entity_id from {{ ref('cleaned_events') }} where event_type = 'parcel.inducted'
  )
