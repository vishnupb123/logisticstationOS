-- One row per parcel: the key Cycle-1 lifecycle timestamps and
-- attributes, derived purely from its own event history — the
-- analytical-layer analogue of
-- backend/app/services/event_ingestion.py's projector, built for
-- querying rather than application state. Deliberately duplicates that
-- projector's *logic* in SQL rather than reusing it directly: the two
-- have different jobs (one maintains Postgres's current-state rows per
-- write, this one restates the same facts as a batch, queryable view)
-- and different failure modes worth keeping separately testable.
select
    parcel_id,
    min(case when event_type = 'parcel.inducted' then occurred_at end) as inducted_at,
    max(classification) as classification,
    min(
        case when event_type = 'parcel.sort_attempted' and sort_outcome = 'jackpot'
        then occurred_at end
    ) as first_jackpot_diverted_at,
    max(case when event_type = 'parcel.jackpot_cleared' then occurred_at end) as jackpot_cleared_at,
    max(
        case when event_type = 'parcel.sort_attempted' and sort_outcome = 'sorted'
        then occurred_at end
    ) as sorted_at,
    max(
        case when event_type = 'parcel.sort_attempted' and sort_outcome = 'sorted'
        then aisle_code end
    ) as aisle_code,
    max(case when event_type = 'parcel.stowed' then occurred_at end) as stowed_at,
    max(case when event_type = 'parcel.stowed' then bag_code end) as bag_code,
    max(case when event_type = 'parcel.stowed' then stower_code end) as stower_code
from {{ ref('curated_parcel_events') }}
group by parcel_id
