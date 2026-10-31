-- Timestamp validity (docs/ENGINEERING_ROADMAP.md Milestone 3 test
-- category): an event cannot be recorded before it happened. Fails if
-- any row violates it.
select *
from {{ ref('cleaned_events') }}
where occurred_at > recorded_at
