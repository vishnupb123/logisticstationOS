-- Metric-contract requirement (docs/ENGINEERING_ROADMAP.md Milestone 3
-- test category): dwell time (induct -> stow) can never be negative —
-- a stow event timestamped before its own induct event indicates
-- corrupt data, not a valid measurement.
select *
from {{ ref('metric_parcel_dwell_time') }}
where dwell_seconds < 0
