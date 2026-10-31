-- Metric-contract requirement (docs/ENGINEERING_ROADMAP.md Milestone 3
-- test category): a station can't clear more parcels from jackpot than
-- were ever diverted into it.
select *
from {{ ref('metric_jackpot_volume') }}
where currently_in_jackpot < 0
