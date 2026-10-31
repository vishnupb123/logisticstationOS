-- Metric contract: docs/OPERATIONAL_DOMAIN_MODEL.md §4.1 "Jackpot
-- volume" — status: proposed. count(jackpot-divert events) -
-- count(jackpot-clear events), as of the latest event in this export.
with diverts as (
    select event_id
    from {{ ref('curated_parcel_events') }}
    where event_type = 'parcel.sort_attempted' and sort_outcome = 'jackpot'
),
clears as (
    select event_id
    from {{ ref('curated_parcel_events') }}
    where event_type = 'parcel.jackpot_cleared'
)
select
    (select count(*) from diverts) as cumulative_diverts,
    (select count(*) from clears) as cumulative_clears,
    (select count(*) from diverts) - (select count(*) from clears) as currently_in_jackpot
