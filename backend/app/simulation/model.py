"""The digital twin itself: a SimPy discrete-event model of Cycle 1
(truck arrival -> induct -> classify -> sort -> [jackpot/clear] ->
stow), per docs/DIGITAL_TWIN_SPEC.md and ADR-0006.

Output is a list of the exact same EventEnvelope objects the real
ingestion pipeline uses (app/events/schemas.py), tagged
source_kind=SIMULATED — not a separate ad hoc format. This is a
deliberate architectural choice (recorded in ADR-0006's amendment):
simulated events are written straight to Parquet
(app/simulation/export.py), never through PostgreSQL/EventStore, since
a simulation run isn't "operational truth" (ADR-0002) — but they're
schema-identical to what EventStore would have accepted, so the same
dbt models (backend/analytics/) read either without caring which
produced them.

Unlike the Milestone 2 synthetic generator — which just assigns
plausible random timestamps — this model has real resource contention:
a shared induct station, a shared stower pool, and per-aisle hampers
with finite capacity. Jackpot diversion emerges from hampers actually
being full when a sort is attempted, not a probability knob.

High-value/sideline/future-date/exception classifications stop at
PENDING_EXCEPTION, same scope boundary as Milestone 2 — the cage
workflow isn't modeled at the application layer either, so the twin
doesn't invent one.
"""

import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import simpy

from app.core.determinism import rng_hex, rng_uuid
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
from app.simulation.config import ScenarioConfig

SOURCE = "digital_twin:v1"
_ORIGINS = ("ORIGIN-NORTH", "ORIGIN-SOUTH", "ORIGIN-FERRY-1")
_EXCEPTION_CLASSIFICATIONS = (
    ParcelClassification.SIDELINE,
    ParcelClassification.HIGH_VALUE,
    ParcelClassification.FUTURE_DATE,
    ParcelClassification.EXCEPTION,
)
_SIMULATION_EPOCH = datetime(2026, 1, 1, 2, 30, tzinfo=UTC)


@dataclass
class SimulationResult:
    events: list[EventEnvelope]
    run_id: uuid.UUID
    scenario_name: str
    seed: int
    simpy_version: str
    generated_at: datetime


# --- Mutable simulation state (plain Python objects — SimPy processes
# are cooperatively scheduled, so there's no concurrent-mutation risk
# between yield points). -------------------------------------------------


@dataclass
class _Hamper:
    capacity: int
    level: int = 0


@dataclass
class _Counter:
    value: int = 0


class _JackpotSignal:
    """A periodically-replaced SimPy event: every parcel currently
    waiting in jackpot yields on `.wait()`; `.clear()` wakes all of them
    at once, as a single supervisory clearing action
    (docs/OPERATIONAL_DOMAIN_MODEL.md: "jackpot must be cleared and
    reintroduced"), not one event per parcel.
    """

    def __init__(self, env: simpy.Environment):
        self._env = env
        self.event = env.event()

    def wait(self) -> simpy.Event:
        return self.event

    def clear(self) -> None:
        old, self.event = self.event, self._env.event()
        old.succeed()


@dataclass
class _Context:
    rng: random.Random
    config: ScenarioConfig
    env: simpy.Environment
    aisle_codes: list[str]
    hampers: dict[str, _Hamper]
    induct_station: simpy.Resource
    stower_pool: simpy.Resource
    jackpot_signal: _JackpotSignal
    parcels_in_flight: _Counter
    trucks_remaining: _Counter
    events: list[EventEnvelope] = field(default_factory=list)

    def at(self, now: float) -> datetime:
        return _SIMULATION_EPOCH + timedelta(seconds=now)

    def emit(
        self,
        event_type: str,
        entity_type: str,
        entity_id: uuid.UUID,
        correlation_id: str,
        provenance: str,
        payload: dict,
    ) -> None:
        # Every event this twin produces is SIMULATED, full stop — unlike
        # the Milestone 2 generator (which stands in for what a real
        # scanner/system would have produced, and so tags source_kind
        # per event type as physical_observation/system_recorded), there
        # is no real-world instrument behind anything here. Tagging
        # these any other way would misrepresent simulated output as a
        # stand-in for a real observation, which is exactly what
        # source_kind exists to prevent (docs/DATA_ARCHITECTURE.md).
        self.events.append(
            EventEnvelope(
                event_id=rng_uuid(self.rng),
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                correlation_id=correlation_id,
                occurred_at=self.at(self.env.now),
                source=SOURCE,
                source_kind=EventSourceKind.SIMULATED,
                provenance=provenance,
                payload=payload,
            )
        )


# --- Processes ------------------------------------------------------------


def _truck_process(ctx: _Context, truck_index: int, arrival_offset_minutes: float):
    yield ctx.env.timeout(arrival_offset_minutes * 60)

    truck_id = rng_uuid(ctx.rng)
    external_code = f"TRK-{ctx.config.seed:04d}-{truck_index:03d}"
    pallet_count = ctx.rng.randint(
        ctx.config.truck_arrivals.pallet_count_min, ctx.config.truck_arrivals.pallet_count_max
    )

    ctx.emit(
        TRUCK_ARRIVED,
        "truck",
        truck_id,
        external_code,
        "simulation:truck_arrival",
        {
            "origin": ctx.rng.choice(_ORIGINS),
            "scheduled_arrival_at": ctx.at(ctx.env.now).isoformat(),
            "pallet_count": pallet_count,
        },
    )

    yield ctx.env.timeout(ctx.config.truck_arrivals.unload_duration_minutes * 60)

    ctx.emit(
        TRUCK_UNLOADED,
        "truck",
        truck_id,
        external_code,
        "simulation:truck_unload",
        {"pallet_count_unloaded": pallet_count},
    )

    for _ in range(ctx.config.parcels.parcels_per_truck):
        ctx.parcels_in_flight.value += 1
        ctx.env.process(_parcel_process(ctx, truck_id, external_code))
        # Crashers feed parcels onto the belt one at a time, not all at once.
        yield ctx.env.timeout(2)

    ctx.trucks_remaining.value -= 1


def _parcel_process(ctx: _Context, truck_id: uuid.UUID, truck_external_code: str):
    parcel_id = rng_uuid(ctx.rng)
    tracking_id = f"SIM-{rng_hex(ctx.rng, 5)}"
    sal_label = f"SAL-{rng_hex(ctx.rng, 4)}"

    with ctx.induct_station.request() as req:
        yield req
        yield ctx.env.timeout(ctx.config.parcels.induct_duration_seconds)

    ctx.emit(
        PARCEL_INDUCTED,
        "parcel",
        parcel_id,
        tracking_id,
        "simulation:induct_scan",
        {
            "truck_id": str(truck_id),
            "tracking_id": tracking_id,
            "origin": truck_external_code,
            "sal_label": sal_label,
        },
    )

    classification = _pick_classification(ctx.rng, ctx.config.parcels.exception_rate)
    ctx.emit(
        PARCEL_CLASSIFIED,
        "parcel",
        parcel_id,
        tracking_id,
        "simulation:classification",
        {"classification": classification.value},
    )

    if classification != ParcelClassification.NORMAL_CYCLE1:
        # Exception/sideline/high-value/future-date cage workflows aren't
        # modeled yet (docs/ENGINEERING_ROADMAP.md Milestone 2 scope) —
        # the parcel's simulated lifecycle legitimately stops here too.
        ctx.parcels_in_flight.value -= 1
        return

    aisle_code = ctx.rng.choice(ctx.aisle_codes)
    hamper = ctx.hampers[aisle_code]
    while True:
        if hamper.level < hamper.capacity:
            hamper.level += 1
            ctx.emit(
                PARCEL_SORT_ATTEMPTED,
                "parcel",
                parcel_id,
                tracking_id,
                "simulation:sort_cluster",
                {"outcome": SortAttemptOutcome.SORTED.value, "aisle_code": aisle_code},
            )
            break

        ctx.emit(
            PARCEL_SORT_ATTEMPTED,
            "parcel",
            parcel_id,
            tracking_id,
            "simulation:sort_cluster",
            {"outcome": SortAttemptOutcome.JACKPOT.value},
        )
        yield ctx.jackpot_signal.wait()
        ctx.emit(
            PARCEL_JACKPOT_CLEARED,
            "parcel",
            parcel_id,
            tracking_id,
            "simulation:jackpot_clear",
            {"note": "reintroduced after jackpot clear"},
        )
        # Loop retries the same assigned aisle — hamper state is
        # re-checked fresh; stowers may have drained it by now.

    with ctx.stower_pool.request() as req:
        yield req
        yield ctx.env.timeout(ctx.config.parcels.stow_duration_seconds)

    hamper.level -= 1
    stower_code = f"STOWER-{ctx.rng.randint(1, ctx.config.resources.stower_count):02d}"
    bag_code = f"BAG-{aisle_code}-{ctx.rng.randint(1, 20):03d}"
    ctx.emit(
        PARCEL_STOWED,
        "parcel",
        parcel_id,
        tracking_id,
        "simulation:stow",
        {"bag_code": bag_code, "stower_code": stower_code},
    )
    ctx.parcels_in_flight.value -= 1


def _jackpot_clearing_process(ctx: _Context):
    """Runs until every truck has finished spawning its parcels AND
    every one of those parcels has reached a terminal state. Checking
    only parcels_in_flight would let this process see "0 parcels yet"
    before the first truck has even arrived and exit immediately —
    trucks_remaining guards against that race.
    """
    interval_seconds = ctx.config.resources.jackpot_clear_interval_minutes * 60
    while ctx.trucks_remaining.value > 0 or ctx.parcels_in_flight.value > 0:
        yield ctx.env.timeout(interval_seconds)
        ctx.jackpot_signal.clear()


def _pick_classification(rng: random.Random, exception_rate: float) -> ParcelClassification:
    if rng.random() < exception_rate:
        return rng.choice(_EXCEPTION_CLASSIFICATIONS)
    return ParcelClassification.NORMAL_CYCLE1


# --- Entry point ------------------------------------------------------


def run_scenario(config: ScenarioConfig) -> SimulationResult:
    rng = random.Random(config.seed)
    env = simpy.Environment()

    aisle_codes = [f"A{i}" for i in range(1, config.station_layout.cluster_a_aisle_count + 1)] + [
        f"B{i}" for i in range(1, config.station_layout.cluster_b_aisle_count + 1)
    ]
    hampers = {
        code: _Hamper(capacity=config.station_layout.hamper_capacity) for code in aisle_codes
    }

    ctx = _Context(
        rng=rng,
        config=config,
        env=env,
        aisle_codes=aisle_codes,
        hampers=hampers,
        induct_station=simpy.Resource(env, capacity=config.resources.induct_capacity),
        stower_pool=simpy.Resource(env, capacity=config.resources.stower_count),
        jackpot_signal=_JackpotSignal(env),
        parcels_in_flight=_Counter(),
        trucks_remaining=_Counter(value=config.truck_arrivals.truck_count),
    )

    for truck_index in range(config.truck_arrivals.truck_count):
        arrival_offset = (
            config.truck_arrivals.first_arrival_offset_minutes
            + truck_index * config.truck_arrivals.arrival_interval_minutes
        )
        env.process(_truck_process(ctx, truck_index, arrival_offset))

    env.process(_jackpot_clearing_process(ctx))

    env.run()

    return SimulationResult(
        events=ctx.events,
        # Deliberately NOT drawn from the seeded rng, unlike every other
        # id in this module — a run_id identifies one execution among
        # possibly-many identical seeded replays; it is metadata about
        # *this invocation*, not part of the deterministic simulated
        # content, so it's exempt from the determinism requirement that
        # everything else here follows.
        run_id=uuid.uuid4(),
        scenario_name=config.name,
        seed=config.seed,
        simpy_version=simpy.__version__,
        generated_at=datetime.now(UTC),
    )
