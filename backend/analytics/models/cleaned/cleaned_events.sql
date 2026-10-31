-- Cleaned layer: typed envelope fields, payload cast to JSON for
-- downstream parsing. Payload keys stay unflattened here — flattening
-- every possible key before anything needs it would be guessing, not
-- modelling (docs/ENGINEERING_ROADMAP.md: "no dbt model should
-- duplicate application logic without a clear analytical purpose").
select
    event_id,
    event_type,
    entity_type,
    entity_id,
    correlation_id,
    occurred_at,
    recorded_at,
    source,
    source_kind,
    provenance,
    idempotency_key,
    schema_version,
    payload::json as payload
from {{ ref('raw_events') }}
