"""Live, step-by-step playback of a digital-twin run — the "watch the
station work" view. Steps the exact same SimPy model `run_scenario()`
runs (via `setup_simulation`), but in small sim-time increments, and
after each one emits a `LiveSnapshot`: cumulative end-to-end funnel
counts (truck -> induct -> sort -> stow), current work-in-process per
stage, resource utilization, per-aisle hamper levels, and end-to-end
cycle-time statistics computed from the events produced so far.

Same boundaries as every other simulation path (ADR-0006/ADR-0002):
nothing here touches PostgreSQL or disk, and every snapshot is tagged
`source_kind="simulated"` — this is a hypothetical run played back
live, never a live feed of operational truth.
"""

import statistics
from collections.abc import Iterator
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

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
from app.simulation.model import _Context, setup_simulation

# Hard upper bound on frames per stream, independent of caller input —
# a stream must always terminate, whatever step size is requested.
MAX_FRAMES = 2000
_RECENT_EVENT_LIMIT = 12


class FunnelCounts(BaseModel):
    trucks_arrived: int = 0
    trucks_unloaded: int = 0
    parcels_inducted: int = 0
    parcels_exception: int = 0  # classified into an unmodeled exception workflow
    parcels_sorted: int = 0
    jackpot_diverts: int = 0
    jackpot_clears: int = 0
    parcels_stowed: int = 0


class StageWip(BaseModel):
    awaiting_induct: int  # unloaded onto the belt, waiting for an induct station
    inducting: int
    in_jackpot: int
    awaiting_stow: int  # sorted into a hamper, waiting for a stower
    stowing: int


class Utilization(BaseModel):
    induct_busy: int
    induct_capacity: int
    stowers_busy: int
    stower_capacity: int


class HamperLevel(BaseModel):
    aisle_code: str
    level: int
    capacity: int


class DurationStats(BaseModel):
    count: int
    avg_seconds: float | None
    p50_seconds: float | None
    p90_seconds: float | None


class CycleTimes(BaseModel):
    dock_to_stow: DurationStats  # truck arrival -> parcel stowed (true end to end)
    induct_to_sort: DurationStats
    sort_to_stow: DurationStats
    induct_to_stow: DurationStats


class RecentEvent(BaseModel):
    occurred_at: datetime
    event_type: str
    correlation_id: str
    detail: str | None


class LiveSnapshot(BaseModel):
    frame: int
    sim_time_seconds: float
    sim_clock: datetime
    done: bool
    planned_parcels: int
    funnel: FunnelCounts
    wip: StageWip
    utilization: Utilization
    hampers: list[HamperLevel]
    cycle_times: CycleTimes
    recent_events: list[RecentEvent]
    source_kind: Literal["simulated"] = "simulated"


def _duration_stats(values: list[float]) -> DurationStats:
    if not values:
        return DurationStats(count=0, avg_seconds=None, p50_seconds=None, p90_seconds=None)
    ordered = sorted(values)
    p90_index = min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))
    return DurationStats(
        count=len(ordered),
        avg_seconds=statistics.fmean(ordered),
        p50_seconds=statistics.median(ordered),
        p90_seconds=ordered[p90_index],
    )


def _event_detail(event: EventEnvelope) -> str | None:
    payload = event.payload
    if event.event_type == PARCEL_SORT_ATTEMPTED:
        aisle = payload.get("aisle_code")
        return f"{payload.get('outcome')}" + (f" -> {aisle}" if aisle else "")
    if event.event_type == PARCEL_CLASSIFIED:
        return payload.get("classification")
    if event.event_type == PARCEL_STOWED:
        return f"{payload.get('bag_code')} by {payload.get('stower_code')}"
    if event.event_type == TRUCK_ARRIVED:
        return f"{payload.get('origin')}, {payload.get('pallet_count')} pallets"
    return None


class LiveSnapshotTracker:
    """Consumes the twin's event list incrementally (only events added
    since the previous snapshot) and keeps per-parcel lifecycle
    timestamps, so each snapshot costs O(new events), not O(all events).
    """

    def __init__(self, ctx: _Context):
        self._ctx = ctx
        self._cursor = 0
        self._frame = 0
        self.funnel = FunnelCounts()
        self._truck_arrived_at: dict[str, datetime] = {}
        self._parcel_truck: dict[str, str] = {}
        self._inducted_at: dict[str, datetime] = {}
        self._sorted_at: dict[str, datetime] = {}
        self._dock_to_stow: list[float] = []
        self._induct_to_sort: list[float] = []
        self._sort_to_stow: list[float] = []
        self._induct_to_stow: list[float] = []

    def _consume(self, event: EventEnvelope) -> None:
        f = self.funnel
        entity = str(event.entity_id)
        t = event.occurred_at
        if event.event_type == TRUCK_ARRIVED:
            f.trucks_arrived += 1
            self._truck_arrived_at[entity] = t
        elif event.event_type == TRUCK_UNLOADED:
            f.trucks_unloaded += 1
        elif event.event_type == PARCEL_INDUCTED:
            f.parcels_inducted += 1
            self._inducted_at[entity] = t
            self._parcel_truck[entity] = event.payload["truck_id"]
        elif event.event_type == PARCEL_CLASSIFIED:
            if event.payload.get("classification") != "normal_cycle1":
                f.parcels_exception += 1
        elif event.event_type == PARCEL_SORT_ATTEMPTED:
            if event.payload.get("outcome") == "sorted":
                f.parcels_sorted += 1
                self._sorted_at[entity] = t
                if entity in self._inducted_at:
                    self._induct_to_sort.append((t - self._inducted_at[entity]).total_seconds())
            else:
                f.jackpot_diverts += 1
        elif event.event_type == PARCEL_JACKPOT_CLEARED:
            f.jackpot_clears += 1
        elif event.event_type == PARCEL_STOWED:
            f.parcels_stowed += 1
            if entity in self._sorted_at:
                self._sort_to_stow.append((t - self._sorted_at[entity]).total_seconds())
            if entity in self._inducted_at:
                self._induct_to_stow.append((t - self._inducted_at[entity]).total_seconds())
            arrived = self._truck_arrived_at.get(self._parcel_truck.get(entity, ""))
            if arrived is not None:
                self._dock_to_stow.append((t - arrived).total_seconds())

    def snapshot(self, *, done: bool) -> LiveSnapshot:
        ctx = self._ctx
        new_events = ctx.events[self._cursor :]
        for event in new_events:
            self._consume(event)
        self._cursor = len(ctx.events)
        self._frame += 1

        f = self.funnel
        inducting = ctx.induct_station.count
        awaiting_induct = len(ctx.induct_station.queue)
        stowing = ctx.stower_pool.count
        in_jackpot = f.jackpot_diverts - f.jackpot_clears
        awaiting_stow = max(0, f.parcels_sorted - f.parcels_stowed - stowing)

        config = ctx.config
        return LiveSnapshot(
            frame=self._frame,
            sim_time_seconds=ctx.env.now,
            sim_clock=ctx.at(ctx.env.now),
            done=done,
            planned_parcels=config.truck_arrivals.truck_count * config.parcels.parcels_per_truck,
            funnel=f.model_copy(),
            wip=StageWip(
                awaiting_induct=awaiting_induct,
                inducting=inducting,
                in_jackpot=in_jackpot,
                awaiting_stow=awaiting_stow,
                stowing=stowing,
            ),
            utilization=Utilization(
                induct_busy=inducting,
                induct_capacity=config.resources.induct_capacity,
                stowers_busy=stowing,
                stower_capacity=config.resources.stower_count,
            ),
            hampers=[
                HamperLevel(aisle_code=code, level=h.level, capacity=h.capacity)
                for code, h in ctx.hampers.items()
            ],
            cycle_times=CycleTimes(
                dock_to_stow=_duration_stats(self._dock_to_stow),
                induct_to_sort=_duration_stats(self._induct_to_sort),
                sort_to_stow=_duration_stats(self._sort_to_stow),
                induct_to_stow=_duration_stats(self._induct_to_stow),
            ),
            recent_events=[
                RecentEvent(
                    occurred_at=e.occurred_at,
                    event_type=e.event_type,
                    correlation_id=e.correlation_id,
                    detail=_event_detail(e),
                )
                for e in new_events[-_RECENT_EVENT_LIMIT:]
            ],
        )


def iter_live_snapshots(config: ScenarioConfig, *, step_seconds: float) -> Iterator[LiveSnapshot]:
    """Yields one snapshot per `step_seconds` of simulated time until the
    station has drained (every truck has spawned all its parcels and none
    is still in flight), then a final `done=True` snapshot. Deterministic
    for a given config/seed; bounded by MAX_FRAMES regardless.

    Termination is checked on domain state, not `env.peek()`: stepping
    with `env.run(until=...)` leaves SimPy's own until-marker in the
    queue, so "no events scheduled" never becomes true mid-stepping.
    """
    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")
    env, ctx = setup_simulation(config)
    tracker = LiveSnapshotTracker(ctx)

    def drained() -> bool:
        return ctx.trucks_remaining.value == 0 and ctx.parcels_in_flight.value == 0

    yield tracker.snapshot(done=False)
    for _ in range(MAX_FRAMES):
        env.run(until=env.now + step_seconds)
        if drained():
            break
        yield tracker.snapshot(done=False)
    yield tracker.snapshot(done=True)
