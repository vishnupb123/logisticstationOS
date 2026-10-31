-- Metric contract: docs/OPERATIONAL_DOMAIN_MODEL.md §4.1 "Stow
-- throughput" — status: proposed. count(stow events) per unit time,
-- bucketed hourly and by stower.
select
    date_trunc('hour', occurred_at) as hour_bucket,
    stower_code,
    count(*) as parcels_stowed
from {{ ref('curated_parcel_events') }}
where event_type = 'parcel.stowed'
group by 1, 2
order by 1, 2
