"""Deterministic, seeded generation of a synthetic Cycle-1 event stream —
fixture data standing in for real operational events during development
(docs/SECURITY_AND_GOVERNANCE.md: synthetic data only, never real).

Pure: no I/O, no database. Given the same SyntheticScenario (same seed and
parameters), generate_cycle1_events always returns the same events in the
same order — required for reproducibility (docs/DIGITAL_TWIN_SPEC.md
applies the same requirement to the digital twin; this generator commits
to it too, one milestone earlier).

Every piece of randomness — including entity ids and the EventEnvelope's
own event_id, which Pydantic would otherwise fill in from the unseeded
global uuid.uuid4() — is drawn from the one seeded random.Random instance
threaded through every helper below. Reaching for uuid.uuid4() anywhere
in this module would silently break determinism.
"""

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.determinism import rng_hex as _rng_hex
from app.core.determinism import rng_uuid as _rng_uuid
from app.domain.enums import EventSourceKind, ParcelClassification, SortAttemptOutcome
from app.events.event_types import (
    PARCEL_CLASSIFIED,
    PARCEL_INDUCTED,
    PARCEL_JACKPOT_CLEARED,
    PARCEL_SORT_ATTEMPTED,
    PARCEL_STOWED,
    TRUCK_ARRIVED,
    TRUCK_UNLOADED,
)
from app.events.schemas import EventEnvelope

SOURCE = "synthetic_generator:v1"
_ORIGINS = ("ORIGIN-NORTH", "ORIGIN-SOUTH", "ORIGIN-FERRY-1")
_EXCEPTION_CLASSIFICATIONS = (
    ParcelClassification.SIDELINE,
    ParcelClassification.HIGH_VALUE,
    ParcelClassification.FUTURE_DATE,
    ParcelClassification.EXCEPTION,
)


@dataclass(frozen=True)
class SyntheticScenario:
    seed: int
    truck_count: int = 5
    parcels_per_truck: int = 20
    jackpot_rate: float = 0.08
    exception_rate: float = 0.05


def generate_cycle1_events(scenario: SyntheticScenario) -> list[EventEnvelope]:
    rng = random.Random(scenario.seed)
    aisle_codes = [f"A{i}" for i in range(1, 55)] + [f"B{i}" for i in range(1, 69)]
    base_time = datetime(2026, 1, 1, 2, 30, tzinfo=UTC)

    events: list[EventEnvelope] = []
    for truck_index in range(scenario.truck_count):
        truck_id = _rng_uuid(rng)
        external_code = f"TRK-{scenario.seed:04d}-{truck_index:03d}"
        arrival_time = base_time + timedelta(minutes=truck_index * 5)
        pallet_count = rng.randint(4, 10)

        events.append(_truck_arrived(rng, truck_id, external_code, arrival_time, pallet_count))

        unload_time = arrival_time + timedelta(minutes=10)
        events.append(_truck_unloaded(rng, truck_id, external_code, unload_time, pallet_count))

        for parcel_index in range(scenario.parcels_per_truck):
            events.extend(
                _generate_parcel_events(
                    rng=rng,
                    truck_id=truck_id,
                    truck_external_code=external_code,
                    start_time=unload_time + timedelta(seconds=parcel_index * 3),
                    aisle_codes=aisle_codes,
                    jackpot_rate=scenario.jackpot_rate,
                    exception_rate=scenario.exception_rate,
                )
            )

    return events


def _truck_arrived(rng, truck_id, external_code, arrival_time, pallet_count) -> EventEnvelope:
    return EventEnvelope(
        event_id=_rng_uuid(rng),
        event_type=TRUCK_ARRIVED,
        entity_type="truck",
        entity_id=truck_id,
        correlation_id=external_code,
        occurred_at=arrival_time,
        source=SOURCE,
        source_kind=EventSourceKind.PHYSICAL_OBSERVATION,
        provenance="synthetic:truck_arrival",
        payload={
            "origin": rng.choice(_ORIGINS),
            "scheduled_arrival_at": arrival_time.isoformat(),
            "pallet_count": pallet_count,
        },
    )


def _truck_unloaded(rng, truck_id, external_code, unload_time, pallet_count) -> EventEnvelope:
    return EventEnvelope(
        event_id=_rng_uuid(rng),
        event_type=TRUCK_UNLOADED,
        entity_type="truck",
        entity_id=truck_id,
        correlation_id=external_code,
        occurred_at=unload_time,
        source=SOURCE,
        source_kind=EventSourceKind.SYSTEM_RECORDED,
        provenance="synthetic:truck_unload",
        payload={"pallet_count_unloaded": pallet_count},
    )


def _generate_parcel_events(
    *,
    rng: random.Random,
    truck_id: uuid.UUID,
    truck_external_code: str,
    start_time: datetime,
    aisle_codes: list[str],
    jackpot_rate: float,
    exception_rate: float,
) -> list[EventEnvelope]:
    parcel_id = _rng_uuid(rng)
    tracking_id = f"SYN-{_rng_hex(rng, 5)}"
    sal_label = f"SAL-{_rng_hex(rng, 4)}"
    t = start_time

    events = [
        EventEnvelope(
            event_id=_rng_uuid(rng),
            event_type=PARCEL_INDUCTED,
            entity_type="parcel",
            entity_id=parcel_id,
            correlation_id=tracking_id,
            occurred_at=t,
            source=SOURCE,
            source_kind=EventSourceKind.PHYSICAL_OBSERVATION,
            provenance="synthetic:induct_scan",
            payload={
                "truck_id": str(truck_id),
                "tracking_id": tracking_id,
                "origin": truck_external_code,
                "sal_label": sal_label,
            },
        )
    ]

    classification = _pick_classification(rng, exception_rate)
    t += timedelta(seconds=2)
    events.append(
        EventEnvelope(
            event_id=_rng_uuid(rng),
            event_type=PARCEL_CLASSIFIED,
            entity_type="parcel",
            entity_id=parcel_id,
            correlation_id=tracking_id,
            occurred_at=t,
            source=SOURCE,
            source_kind=EventSourceKind.SYSTEM_RECORDED,
            provenance="synthetic:classification",
            payload={"classification": classification.value},
        )
    )

    if classification != ParcelClassification.NORMAL_CYCLE1:
        # Exception/sideline/high-value/future-date cage workflows aren't
        # modeled yet (docs/ENGINEERING_ROADMAP.md Milestone 2 scope) —
        # the parcel's event stream legitimately stops here.
        return events

    t += timedelta(seconds=3)
    if rng.random() < jackpot_rate:
        events.append(_sort_attempted(rng, parcel_id, tracking_id, t, SortAttemptOutcome.JACKPOT))
        t += timedelta(minutes=rng.randint(2, 15))
        events.append(_jackpot_cleared(rng, parcel_id, tracking_id, t))
        t += timedelta(seconds=3)

    aisle_code = rng.choice(aisle_codes)
    events.append(
        _sort_attempted(rng, parcel_id, tracking_id, t, SortAttemptOutcome.SORTED, aisle_code)
    )

    t += timedelta(minutes=rng.randint(5, 30))
    bag_code = f"BAG-{aisle_code}-{rng.randint(1, 20):03d}"
    stower_code = f"STOWER-{rng.randint(1, 10):02d}"
    events.append(_stowed(rng, parcel_id, tracking_id, t, bag_code, stower_code))

    return events


def _sort_attempted(
    rng, parcel_id, tracking_id, occurred_at, outcome, aisle_code=None
) -> EventEnvelope:
    payload = {"outcome": outcome.value}
    if aisle_code:
        payload["aisle_code"] = aisle_code
    return EventEnvelope(
        event_id=_rng_uuid(rng),
        event_type=PARCEL_SORT_ATTEMPTED,
        entity_type="parcel",
        entity_id=parcel_id,
        correlation_id=tracking_id,
        occurred_at=occurred_at,
        source=SOURCE,
        source_kind=EventSourceKind.PHYSICAL_OBSERVATION,
        provenance="synthetic:sort_cluster",
        payload=payload,
    )


def _jackpot_cleared(rng, parcel_id, tracking_id, occurred_at) -> EventEnvelope:
    return EventEnvelope(
        event_id=_rng_uuid(rng),
        event_type=PARCEL_JACKPOT_CLEARED,
        entity_type="parcel",
        entity_id=parcel_id,
        correlation_id=tracking_id,
        occurred_at=occurred_at,
        source=SOURCE,
        source_kind=EventSourceKind.SYSTEM_RECORDED,
        provenance="synthetic:jackpot_clear",
        payload={"note": "reintroduced after jackpot clear"},
    )


def _stowed(rng, parcel_id, tracking_id, occurred_at, bag_code, stower_code) -> EventEnvelope:
    return EventEnvelope(
        event_id=_rng_uuid(rng),
        event_type=PARCEL_STOWED,
        entity_type="parcel",
        entity_id=parcel_id,
        correlation_id=tracking_id,
        occurred_at=occurred_at,
        source=SOURCE,
        source_kind=EventSourceKind.PHYSICAL_OBSERVATION,
        provenance="synthetic:stow",
        payload={"bag_code": bag_code, "stower_code": stower_code},
    )


def _pick_classification(rng: random.Random, exception_rate: float) -> ParcelClassification:
    if rng.random() < exception_rate:
        return rng.choice(_EXCEPTION_CLASSIFICATIONS)
    return ParcelClassification.NORMAL_CYCLE1
