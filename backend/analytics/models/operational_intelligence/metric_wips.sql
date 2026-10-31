-- Metric contract: docs/OPERATIONAL_DOMAIN_MODEL.md §4.1 "WIPS (Work in
-- Process)" — status: proposed. count(parcels inducted but not yet
-- confirmed stowed), as a snapshot as of the latest event in this
-- export (a batch export is never "live" — see
-- docs/DATA_ARCHITECTURE.md). pending_exception parcels are excluded:
-- their cage/exception workflow isn't modeled
-- (docs/ENGINEERING_ROADMAP.md Milestone 2 scope note), so they're
-- neither "in process" toward stow nor resolved — just out of scope,
-- not zero.
select
    count(*) as wip_count
from {{ ref('curated_parcel_lifecycle') }}
where inducted_at is not null
  and stowed_at is null
  and classification = 'normal_cycle1'
