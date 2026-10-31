-- Metric contract: docs/OPERATIONAL_DOMAIN_MODEL.md §4.1 "Induct
-- throughput" — status: proposed. count(induct events) / time_window,
-- bucketed hourly.
select
    date_trunc('hour', occurred_at) as hour_bucket,
    count(*) as parcels_inducted
from {{ ref('cleaned_events') }}
where event_type = 'parcel.inducted'
group by 1
order by 1
