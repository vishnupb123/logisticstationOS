"""The Station Operations Twin (v2): a package-, associate-, route- and
driver-level SimPy model of one operating day (ADR-0011/0012).

Flow: linehauls (true vs. revealed ferry delay) -> yard -> dock door / unload
sequence -> induct lines (scan defects -> problem solve) -> high-value cage
(custody scans) or sort -> stow into aisle bays (overflow -> jackpot) ->
cycle pick start (induct blocked, un-stowed volume rolls over; stowers and
inductors convert to pickers) -> picklists by priority -> carts -> staging
-> DSP driver check-in -> load -> depart -> stop-by-stop delivery attempts
-> return, swipe-to-finish, RTS.

Associates are individual workers with a role, skill and live task, so
labor can be rebalanced mid-shift. Every lever and every disruption is an
`Intervention` applied at a sim minute; replaying the same config plus the
same intervention log reproduces a run exactly, which is what makes
counterfactual planning (app/agents/station_ops/) possible.

Determinism: all per-package / route / driver / associate randomness is
pre-drawn at construction from seeded RNGs, independent of process order.
"""

import math
import random
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Literal

import simpy
from pydantic import BaseModel, Field

from app.core.determinism import rng_hex
from app.simulation.station_ops.config import Disruption, StationOpsConfig

SERIES_BUCKET_MINUTES = 15
WIP_SAMPLE_MINUTES = 5
MAX_CUTOFF_EXTENSION_MINUTES = 45
MAX_SPARE_LINES = 2
DAY_END_MINUTE = 23 * 60
_IDLE_POLL_S = 120
_MISSORT_REWORK_S = 40
_PROBLEM_SECONDS = {
    "no_read": 240,
    "multi_read": 180,
    "misapplied_label": 150,
    "damaged": 300,
    "jackpot": 60,
}
SECTORS = {"N": (45, 135), "W": (135, 225), "S": (225, 315), "E": (-45, 45)}

ActionKind = Literal[
    "add_stowers",
    "add_pickers",
    "open_induct_line",
    "extend_cutoff",
    "priority_late_linehauls",
    "move_associates",
    "resequence_unload",
    "prioritize_route",
    "sideline_route",
    "unsideline_route",
    "move_route_wave",
    "notify_drivers",
    "reassign_standby",
    "notify_swipe_finish",
    "start_scrub",
    "inject_disruption",
]


class Intervention(BaseModel):
    """A lever, coordination action, or injected disruption applied at
    `at_minute`. `amount` = headcount / minutes / waves; `target` = route id,
    trip id, role, sector, etc.; `params` carries anything else."""

    kind: ActionKind
    amount: float = 1
    at_minute: float = Field(0, ge=0)
    target: str | None = None
    params: dict = {}
    source: str = "manual"


# --- entities ----------------------------------------------------------------


@dataclass
class _Pkg:
    idx: int
    tracking_id: str
    trip: int  # -1 = carry-over / surge
    route: int
    hv: bool
    manifested: bool
    read_u: float
    missort: bool
    missort_caught: bool
    damaged: bool
    damaged_unrecoverable: bool
    deliver_u: float
    customer_return: bool
    induct_mult: float
    stow_mult: float
    carryover: bool = False
    status: str = "pending_receive"
    problem: str | None = None
    reworked: bool = False
    line: int | None = None
    location: str | None = None
    arrived_at: float | None = None
    inducted_at: float | None = None
    stowed_at: float | None = None
    picked_at: float | None = None
    staged_at: float | None = None
    departed_at: float | None = None
    attempt_at: float | None = None
    attempted: bool | None = None
    delivered: bool | None = None
    custody_scans: int = 0


@dataclass
class _Assoc:
    idx: int
    login: str
    home_role: str
    role: str
    skill: float
    present: bool
    shift_start: float
    line: int | None = None
    vet: bool = False
    task: str = "off_shift"
    task_ref: str | None = None
    task_started: float | None = None
    last_activity: float | None = None
    location: str = "—"
    units: int = 0
    busy_s: float = 0.0
    idle_s: float = 0.0
    idle_since: float | None = None
    longest_idle_s: float = 0.0
    history: list = field(default_factory=list)


@dataclass
class _Route:
    idx: int
    route_id: str
    cluster: str
    aisle: str
    wave: int
    original_wave: int
    stage_by: float
    planned_depart: float
    original_depart: float
    duration_hours: float
    staging_location: str
    dsp: str
    angle: float
    radius_km: float
    packages: list[int] = field(default_factory=list)
    priority: int = 0
    sidelined: bool = False
    status: str = "not_ready"  # not_ready, ready, picking, staging, staged, loading, departed
    picker: str | None = None
    pick_started_at: float | None = None
    pick_eta: float | None = None
    picked_at: float | None = None
    bags: int = 0
    carts: int = 0
    carts_staged: int = 0
    hv_pending: int = 0
    staged_at: float | None = None
    departed_at: float | None = None
    driver: int | None = None
    picked_count: int = 0
    not_attempted: int = 0
    failed: int = 0
    stops: int = 0
    moved_waves: int = 0


@dataclass
class _Driver:
    idx: int
    driver_id: str
    dsp: str
    route: int
    home: tuple[float, float]
    travel_s: float
    late_s: float
    recoverable_s: float
    no_show: bool
    forget_swipe: bool
    standby: bool = False
    # off_duty, en_route, checked_in, loading, on_road, released
    state: str = "off_duty"
    notified_at: float | None = None
    leave_at: float | None = None
    arrived_at: float | None = None
    departed_at: float | None = None
    return_at: float | None = None
    swiped_at: float | None = None
    swipe_notified: bool = False
    extra_travel_s: float = 0.0
    early_s: float = 0.0
    wake: object = None


@dataclass
class _Trip:
    idx: int
    status: str = "in_transit"  # in_transit, in_yard, unloading, arrived, cancelled
    door: int | None = None
    yard_at: float | None = None
    arrived_at: float | None = None
    unloaded_at: float | None = None
    priority: int = 0
    sequence: int | None = None


class _Queue:
    """Two-level FIFO queue with cancellable gets and in-place promotion."""

    def __init__(self, env: simpy.Environment):
        self.env = env
        self.hi: deque = deque()
        self.lo: deque = deque()
        self._waiters: deque = deque()

    def __len__(self) -> int:
        return len(self.hi) + len(self.lo)

    def items(self):
        return [*self.hi, *self.lo]

    def put(self, item, *, hi: bool = False) -> None:
        (self.hi if hi else self.lo).append(item)
        self._dispatch()

    def get(self) -> simpy.Event:
        ev = self.env.event()
        self._waiters.append(ev)
        self._dispatch()
        return ev

    def cancel(self, ev: simpy.Event) -> None:
        if not ev.triggered and ev in self._waiters:
            self._waiters.remove(ev)

    def promote(self, predicate) -> int:
        keep, moved = deque(), 0
        for item in self.lo:
            if predicate(item):
                self.hi.append(item)
                moved += 1
            else:
                keep.append(item)
        self.lo = keep
        return moved

    def _dispatch(self) -> None:
        while self._waiters and (self.hi or self.lo):
            ev = self._waiters.popleft()
            if ev.triggered:
                continue
            ev.succeed(self.hi.popleft() if self.hi else self.lo.popleft())


def clock(minute: float) -> str:
    m = int(round(minute))
    day, m = divmod(m, 1440)
    label = f"{m // 60:02d}:{m % 60:02d}"
    return label if day == 0 else f"{label}+{day}d"


def sector_of(x: float, y: float) -> str:
    a = math.degrees(math.atan2(y, x)) % 360
    if 45 <= a < 135:
        return "N"
    if 135 <= a < 225:
        return "W"
    if 225 <= a < 315:
        return "S"
    return "E"


class StationOpsTwin:
    def __init__(self, config: StationOpsConfig, interventions: list[Intervention] | None = None):
        self.config = config
        self.env = simpy.Environment()
        c = config

        self.cutoff = c.cycle.pick_start_minute * 60
        self.cutoff_extension_minutes = 0.0
        self.priority_late = False
        self.pick_started = False
        self.departures_done = False
        self.day_complete = False
        self.applied: list[dict] = []
        self.events: deque = deque(maxlen=400)
        self.disruptions_seen: list[dict] = []
        self.counters: Counter = Counter()
        self.line_stats: dict[int, Counter] = defaultdict(Counter)
        self.cluster_stats: dict[str, Counter] = defaultdict(Counter)
        self._inducted_times: list[float] = []
        self._stowed_times: list[float] = []
        self._wip_samples: list[bool] = []
        self.series: dict[str, list[float]] = defaultdict(list)
        self.flex_remaining = c.labor.flex_pool
        self.standby_remaining = {d.code: d.standby_drivers for d in c.dispatch.dsps}
        self.scrubs: list[dict] = []
        self.weather_mult: list[tuple[float, float]] = []
        self.scanner_mult: list[tuple[int, float, float, float]] = []
        self.line_down_windows: list[tuple[int, float, float, str]] = [
            (o.line, o.start_minute * 60, (o.start_minute + o.duration_minutes) * 60, "planned")
            for o in c.induct.outages
        ]
        self.extra_lines = 0

        self._build_routes()
        self._build_packages()
        self._build_associates()
        self._build_drivers()
        self._build_backlog()
        self.trips = [_Trip(i) for i in range(len(c.linehauls))]
        self.aisle_level: Counter = Counter()
        self.aisle_capacity = self._aisle_capacity()

        self.induct_q = _Queue(self.env)
        self.stow_q = _Queue(self.env)
        self.problem_q = _Queue(self.env)
        self.hv_q = _Queue(self.env)
        self.yard: list[int] = []
        self.doors_free = c.doors
        self._free_doors = list(range(1, c.doors + 1))
        self._door_wake = self.env.event()
        self._staged_events: dict[int, simpy.Event] = {}

        for i in range(len(c.linehauls)):
            self.env.process(self._trip_process(i))
        self.env.process(self._dock_process())
        for a in list(self.assocs):
            self.env.process(self._assoc_proc(a))
        for d in list(self.drivers):
            self.env.process(self._driver_proc(d))
        self.env.process(self._cycle_process())
        self.env.process(self._sampler())
        for p in self._carryover_ids:
            self.env.process(self._carryover_arrival(p))
        for dis in c.disruptions:
            self.env.process(self._scheduled(self._disruption_iv(dis)))
        for iv in interventions or []:
            self.env.process(self._scheduled(iv))

    # --- construction -------------------------------------------------------

    def _build_routes(self) -> None:
        c, o = self.config, self.config.outbound
        rng = random.Random(f"routes:{c.seed}")
        waves = o.wave_stage_by_minutes
        self.aisles = [
            f"{cl}{i + 1:02d}" for cl in c.sort.clusters for i in range(c.sort.aisles_per_cluster)
        ]
        self.routes: list[_Route] = []
        dsps = [d.code for d in c.dispatch.dsps]
        for i in range(o.routes):
            w = i * len(waves) // o.routes
            aisle = self.aisles[i % len(self.aisles)]
            depart = (waves[w] + o.depart_after_stage_by_minutes) * 60
            self.routes.append(
                _Route(
                    idx=i,
                    route_id=f"R-{i + 1:03d}",
                    cluster=aisle[0],
                    aisle=aisle,
                    wave=w,
                    original_wave=w,
                    stage_by=waves[w] * 60,
                    planned_depart=depart,
                    original_depart=depart,
                    duration_hours=rng.uniform(
                        o.route_duration_min_hours, o.route_duration_max_hours
                    ),
                    staging_location=f"STG-{'AB'[i % 2]}{i // 2 + 1:02d}",
                    dsp=dsps[i % len(dsps)],
                    angle=(360 * i / o.routes + rng.uniform(-8, 8)) % 360,
                    radius_km=rng.uniform(4, 14),
                )
            )

    def _new_pkg(self, rng: random.Random, trip: int, *, carryover=False, manifested=None) -> _Pkg:
        q, s = self.config.quality, self.config.sort
        missort = rng.random() < s.missort_rate
        damaged = rng.random() < q.damaged_rate
        pkg = _Pkg(
            idx=len(self.pkgs),
            tracking_id=f"PKG{rng_hex(rng, 5)}",
            trip=trip,
            route=rng.randrange(len(self.routes)),
            hv=rng.random() < q.high_value_rate,
            manifested=(rng.random() >= q.unmanifested_rate) if manifested is None else manifested,
            read_u=rng.random(),
            missort=missort,
            missort_caught=missort and rng.random() < s.missort_catch_rate,
            damaged=damaged,
            damaged_unrecoverable=damaged and rng.random() < q.damaged_unrecoverable_share,
            deliver_u=rng.random(),
            customer_return=rng.random() < self.config.dispatch.customer_return_rate,
            induct_mult=rng.lognormvariate(-0.02, 0.2),
            stow_mult=rng.lognormvariate(-0.08, 0.4),
            carryover=carryover,
        )
        self.pkgs.append(pkg)
        self.routes[pkg.route].packages.append(pkg.idx)
        return pkg

    def _build_packages(self) -> None:
        c = self.config
        rng = random.Random(f"packages:{c.seed}:{c.name}")
        self.pkgs: list[_Pkg] = []
        self.trip_pkgs: list[list[int]] = []
        for t_idx, trip in enumerate(c.linehauls):
            ids = []
            for _ in range(trip.volume):
                pkg = self._new_pkg(rng, t_idx)
                if trip.cancelled:
                    pkg.status = "cancelled_inbound"
                ids.append(pkg.idx)
            self.trip_pkgs.append(ids)
        crng = random.Random(f"carryover:{c.seed}")
        self._carryover_ids = [
            self._new_pkg(crng, -1, carryover=True).idx
            for _ in range(int(c.planned_volume * c.backlog.rollover_share))
        ]

    def _build_associates(self) -> None:
        c, lab = self.config, self.config.labor
        rng = random.Random(f"associates:{c.seed}")
        start = c.induct.start_minute * 60
        plan = (
            [("induct", start)] * c.induct.lines
            + [("stow", start)] * c.stow.stowers
            + [("problem_solve", start)] * lab.problem_solvers
            + [("high_value", start)] * lab.high_value_associates
            + [("pick", self.cutoff - 15 * 60)] * lab.dedicated_pickers
        )
        self.assocs: list[_Assoc] = []
        line = 1
        for i, (role, shift) in enumerate(plan):
            a = _Assoc(
                idx=i,
                login=f"assoc{rng.randrange(100, 999)}{chr(97 + i % 26)}",
                home_role=role,
                role=role,
                skill=max(0.6, rng.lognormvariate(0, lab.skill_sigma)),
                present=rng.random() < lab.attendance_rate,
                shift_start=shift,
            )
            if role == "induct":
                a.line = line
                line += 1
            self.assocs.append(a)
        # an absent inductor's line is covered by a present stower
        for a in self.assocs:
            if a.role == "induct" and not a.present:
                sub = next((b for b in self.assocs if b.role == "stow" and b.present), None)
                if sub:
                    sub.role, sub.home_role, sub.line = "induct", "induct", a.line
                a.line = None
        self._flex_rng = random.Random(f"flex:{c.seed}")

    def _build_drivers(self) -> None:
        c, d = self.config, self.config.dispatch
        rng = random.Random(f"drivers:{c.driver_seed or c.seed}")
        late_rate = {x.code: x.late_rate for x in d.dsps}
        self.drivers: list[_Driver] = []
        for r in self.routes:
            ang = math.radians(rng.uniform(0, 360))
            dist = rng.uniform(5, 25)
            late = rng.random() < late_rate[r.dsp]
            late_s = (
                rng.lognormvariate(math.log(d.late_mean_minutes) - 0.18, 0.6) * 60 if late else 0.0
            )
            drv = _Driver(
                idx=len(self.drivers),
                driver_id=f"DRV-{rng_hex(rng, 2)}",
                dsp=r.dsp,
                route=r.idx,
                home=(dist * math.cos(ang), dist * math.sin(ang)),
                travel_s=dist / d.drive_speed_kmh * 3600,
                late_s=late_s,
                recoverable_s=late_s * d.notify_recoverable_share,
                no_show=rng.random() < 0.012,
                forget_swipe=rng.random() < d.swipe_forget_rate,
            )
            for key, value in c.driver_overrides.get(r.idx, {}).items():
                setattr(drv, key, value)
            r.driver = drv.idx
            r.stops = math.ceil(len(r.packages) / 1.15) if r.packages else 0
            self.drivers.append(drv)

    def _build_backlog(self) -> None:
        b = self.config.backlog
        rng = random.Random(f"backlog:{self.config.seed}")
        self.backlog: list[dict] = []
        for status, n in (
            ("retained", b.retained),
            ("marked_missing", b.marked_missing),
            ("on_road", b.on_road_unconfirmed),
        ):
            for _ in range(n):
                self.backlog.append(
                    {
                        "tracking_id": f"PKG{rng_hex(rng, 5)}",
                        "status": status,
                        "age_days": rng.choice([1, 1, 2, 2, 3, 4, 5, 7]),
                        "resolution": None,
                    }
                )

    def _aisle_capacity(self) -> dict[str, int]:
        per_aisle = Counter(self.routes[p.route].aisle for p in self.pkgs if not p.hv)
        return {a: math.ceil(n * self.config.sort.bay_headroom) + 5 for a, n in per_aisle.items()}

    # --- helpers ------------------------------------------------------------

    def log(self, kind: str, message: str, **data) -> None:
        self.events.append(
            {
                "minute": self.env.now / 60,
                "clock": clock(self.env.now / 60),
                "kind": kind,
                "message": message,
                **data,
            }
        )

    def line_down(self, line: int, at: float | None = None) -> str | None:
        t = self.env.now if at is None else at
        for ln, s, e, why in self.line_down_windows:
            if ln == line and s <= t < e:
                return why
        return None

    def _line_up_at(self, line: int) -> float:
        t = self.env.now
        ends = [e for ln, s, e, _ in self.line_down_windows if ln == line and s <= t < e]
        return max(ends) if ends else t

    def _scanner_factor(self, line: int) -> float:
        t, f = self.env.now, 1.0
        for ln, s, e, m in self.scanner_mult:
            if ln == line and s <= t < e:
                f *= m
        return f

    def _weather_factor(self, t: float) -> float:
        f = 1.0
        for s, m in self.weather_mult:
            if t >= s:
                f = m
        return f

    def _set_task(self, a: _Assoc, task: str, ref: str | None = None, location: str | None = None):
        now = self.env.now
        if a.idle_since is not None:
            dur = now - a.idle_since
            a.idle_s += dur
            a.longest_idle_s = max(a.longest_idle_s, dur)
            a.idle_since = None
        a.task, a.task_ref, a.task_started = task, ref, now
        if location:
            a.location = location
        a.last_activity = now

    def _go_idle(self, a: _Assoc) -> None:
        if a.idle_since is None:
            a.idle_since = self.env.now
        a.task, a.task_ref = "idle", None

    def total_lines(self) -> int:
        return self.config.induct.lines + self.extra_lines

    def active(self, role: str) -> int:
        return sum(1 for a in self.assocs if a.present and a.role == role and a.task != "off_shift")

    # --- inbound ------------------------------------------------------------

    def _trip_process(self, t: int):
        plan = self.config.linehauls[t]
        trip = self.trips[t]
        if plan.cancelled:
            trip.status = "cancelled"
            return
        yield self.env.timeout(max(0.0, (plan.planned_arrival_minute + plan.delay_minutes) * 60))
        trip.status = "in_yard"
        trip.yard_at = self.env.now
        self.yard.append(t)
        self.log("inbound", f"{plan.trip_id} ({plan.origin}) arrived in yard")
        if not self._door_wake.triggered:
            self._door_wake.succeed()

    def _yard_key(self, t: int):
        plan = self.config.linehauls[t]
        late = plan.delay_minutes > 0 and self.priority_late
        return (-self.trips[t].priority, not late, self.trips[t].yard_at, t)

    def _dock_process(self):
        while True:
            while self.yard and self.doors_free > 0:
                t = min(self.yard, key=self._yard_key)
                self.yard.remove(t)
                self.doors_free -= 1
                self.trips[t].door = self._free_doors.pop(0)
                self.env.process(self._unload(t))
            self._door_wake = self.env.event()
            yield self._door_wake

    def _unload(self, t: int):
        plan, trip = self.config.linehauls[t], self.trips[t]
        trip.status = "unloading"
        trip.arrived_at = self.env.now
        trip.sequence = sum(1 for x in self.trips if x.arrived_at is not None)
        ids = self.trip_pkgs[t]
        unload_s = plan.volume / 1000 * self.config.unload_minutes_per_1000 * 60
        chunks = 4
        for k in range(chunks):
            yield self.env.timeout(unload_s / chunks)
            for idx in ids[k * len(ids) // chunks : (k + 1) * len(ids) // chunks]:
                self._receive(idx, hi=self.priority_late and plan.delay_minutes > 0)
        trip.status = "arrived"
        trip.unloaded_at = self.env.now
        self.doors_free += 1
        self._free_doors.append(trip.door)
        self._free_doors.sort()
        if not self._door_wake.triggered:
            self._door_wake.succeed()

    def _receive(self, idx: int, *, hi: bool = False) -> None:
        pkg = self.pkgs[idx]
        if pkg.status != "pending_receive":
            return
        pkg.arrived_at = self.env.now
        self.counters["arrived"] += 1
        if not pkg.manifested:
            self.counters["unmanifested_arrived"] += 1
        if self.pick_started:
            pkg.status = "rolled_over"
            return
        pkg.status = "pending_induct"
        self.induct_q.put(idx, hi=hi)

    def _carryover_arrival(self, idx: int):
        yield self.env.timeout(self.config.induct.start_minute * 60)
        self._receive(idx)

    # --- associates -----------------------------------------------------------

    def _assoc_proc(self, a: _Assoc):
        if self.env.now < a.shift_start:
            yield self.env.timeout(a.shift_start - self.env.now)
        if a.present:
            a.history.append((self.env.now / 60, a.role))
            self._go_idle(a)
        while not self.departures_done:
            if not a.present or a.role == "off":
                a.task = "off_shift"
                yield self.env.timeout(600)
                continue
            role = a.role
            if role == "induct":
                yield from self._induct_task(a)
            elif role == "stow":
                yield from self._stow_task(a)
            elif role == "pick":
                yield from self._pick_task(a)
            elif role == "problem_solve":
                yield from self._problem_task(a)
            elif role == "high_value":
                yield from self._hv_task(a)
            else:
                yield self.env.timeout(_IDLE_POLL_S)
        a.task = "off_shift"

    def _wait_get(self, q: _Queue, a: _Assoc, timeout_s: float = _IDLE_POLL_S):
        get = q.get()
        yield get | self.env.timeout(timeout_s)
        if not get.triggered:
            q.cancel(get)
            self._go_idle(a)
            return None
        return get.value

    def _until_cutoff(self) -> float:
        return min(_IDLE_POLL_S, max(1.0, self.cutoff - self.env.now))

    def _induct_task(self, a: _Assoc):
        if self.pick_started:
            self.reassign(a, "pick")
            yield self.env.timeout(0)
            return
        line = a.line or 1
        if self.line_down(line):
            self._set_task(a, "line_down", f"L{line}", f"Induct L{line}")
            yield self.env.timeout(
                max(1.0, min(self._line_up_at(line), self.cutoff) - self.env.now)
            )
            return
        idx = yield from self._wait_get(self.induct_q, a, self._until_cutoff())
        if idx is None:
            return
        pkg = self.pkgs[idx]
        pkg.status = "inducting"
        self._set_task(a, "inducting", pkg.tracking_id, f"Induct L{line}")
        dur = 3600 / self.config.induct.rate_pph_per_line / a.skill * pkg.induct_mult
        if not pkg.manifested:
            dur += 10
        yield self.env.timeout(dur)
        a.busy_s += dur
        a.units += 1
        pkg.line = line
        self.counters["induct_attempts"] += 1
        self.line_stats[line]["attempts"] += 1
        ic = self.config.induct
        if not pkg.reworked:
            nr = ic.no_read_rate * self._scanner_factor(line)
            defect = None
            if pkg.read_u < nr:
                defect = "no_read"
            elif pkg.read_u < nr + ic.multi_read_rate:
                defect = "multi_read"
            elif pkg.read_u < nr + ic.multi_read_rate + ic.misapplied_label_rate:
                defect = "misapplied_label"
            elif pkg.damaged:
                defect = "damaged"
            if defect:
                self.counters[defect] += 1
                self.line_stats[line][defect] += 1
                pkg.status, pkg.problem = "problem_solve", defect
                self.problem_q.put(("pkg", idx))
                self._go_idle(a)
                return
        self._inducted(pkg, line)
        self._go_idle(a)

    def _inducted(self, pkg: _Pkg, line: int) -> None:
        pkg.inducted_at = self.env.now
        if self.pick_started:
            pkg.status = "rolled_over"
            return
        self.counters["inducted"] += 1
        self.line_stats[line]["inducted"] += 1
        self._inducted_times.append(self.env.now)
        if pkg.hv:
            pkg.status = "hv_pending_scan_in"
            self.hv_q.put(("scan_in", pkg.idx))
            return
        self.counters["sorted"] += 1
        if pkg.missort:
            self.counters["missorts"] += 1
        pkg.status = "pending_stow"
        self.stow_q.put(pkg.idx)

    def _stow_task(self, a: _Assoc):
        if self.pick_started:
            self.reassign(a, "pick")
            yield self.env.timeout(0)
            return
        idx = yield from self._wait_get(self.stow_q, a, self._until_cutoff())
        if idx is None:
            return
        pkg = self.pkgs[idx]
        route = self.routes[pkg.route]
        pkg.status = "stowing"
        self._set_task(a, "stowing", pkg.tracking_id, f"Aisle {route.aisle}")
        extra = _MISSORT_REWORK_S if pkg.missort and pkg.missort_caught else 0
        dur = 3600 / self.config.stow.rate_pph_per_stower / a.skill * pkg.stow_mult + extra
        yield self.env.timeout(dur)
        a.busy_s += dur
        a.units += 1
        if self.pick_started and route.status not in ("not_ready", "ready"):
            pkg.status = "rolled_over"
            self._go_idle(a)
            return
        if self.aisle_level[route.aisle] >= self.aisle_capacity.get(route.aisle, 10**9):
            pkg.status = "jackpot"
            self.counters["jackpot"] += 1
            self.cluster_stats[route.cluster]["jackpot"] += 1
            self.problem_q.put(("jackpot", idx))
        else:
            self._stowed(pkg, route.aisle)
        self._go_idle(a)

    def _stowed(self, pkg: _Pkg, location: str) -> None:
        route = self.routes[pkg.route]
        pkg.stowed_at = self.env.now
        pkg.status = "stowed"
        pkg.location = location
        if location == route.aisle:
            self.aisle_level[route.aisle] += 1
        self.counters["stowed"] += 1
        self.cluster_stats[route.cluster]["stowed"] += 1
        self._stowed_times.append(self.env.now)

    def _problem_task(self, a: _Assoc):
        item = yield from self._wait_get(self.problem_q, a)
        if item is None:
            return
        kind, idx = item
        pkg = self.pkgs[idx]
        reason = "jackpot" if kind == "jackpot" else pkg.problem or "no_read"
        self._set_task(a, f"problem:{reason}", pkg.tracking_id, "Problem solve")
        dur = _PROBLEM_SECONDS.get(reason, 180) / a.skill
        yield self.env.timeout(dur)
        a.busy_s += dur
        a.units += 1
        self.counters["problems_resolved"] += 1
        if kind == "jackpot":
            route = self.routes[pkg.route]
            if self.pick_started and route.status not in ("not_ready", "ready"):
                pkg.status = "rolled_over"
            else:
                self._stowed(pkg, f"OVERFLOW-{route.cluster}")
            self._go_idle(a)
            return
        if reason == "damaged" and pkg.damaged_unrecoverable:
            pkg.status = "held_damaged"
            self._go_idle(a)
            return
        pkg.reworked = True
        pkg.problem = None
        if self.pick_started:
            pkg.status = "rolled_over"
        else:
            pkg.status = "pending_induct"
            self.induct_q.put(idx, hi=True)
        self._go_idle(a)

    def _hv_task(self, a: _Assoc):
        item = yield from self._wait_get(self.hv_q, a)
        if item is None:
            return
        kind, ref = item
        q = self.config.quality
        if kind == "scan_in":
            pkg = self.pkgs[ref]
            self._set_task(a, "hv_scan_in", pkg.tracking_id, "HV cage")
            dur = q.hv_scan_in_seconds / a.skill
            yield self.env.timeout(dur)
            pkg.status = "hv_in_cage"
            pkg.location = "HV-CAGE"
            pkg.custody_scans += 1
            pkg.stowed_at = self.env.now
            self.counters["hv_caged"] += 1
        else:
            route = self.routes[ref]
            pending = [
                i for i in route.packages if self.pkgs[i].hv and self.pkgs[i].status == "hv_in_cage"
            ]
            self._set_task(a, "hv_handoff", route.route_id, route.staging_location)
            dur = max(1.0, len(pending) * q.hv_handoff_seconds / a.skill)
            yield self.env.timeout(dur)
            for i in pending:
                p = self.pkgs[i]
                p.status, p.picked_at = "picked", self.env.now
                p.custody_scans += 1
                route.picked_count += 1
                self.counters["hv_handed_off"] += 1
            route.hv_pending = 0
            for i in pending:
                if route.carts_staged >= route.carts:
                    self.pkgs[i].status, self.pkgs[i].staged_at = "staged", self.env.now
            self._maybe_staged(route)
        a.busy_s += dur
        a.units += 1
        self._go_idle(a)

    def route_key(self, r: _Route):
        return (-r.priority, r.stage_by, r.idx)

    def _pick_task(self, a: _Assoc):
        if not self.pick_started:
            self._go_idle(a)
            yield self.env.timeout(self._until_cutoff())
            return
        ready = [r for r in self.routes if r.status == "ready" and not r.sidelined]
        if not ready:
            self._go_idle(a)
            if not any(r.status in ("ready",) for r in self.routes):
                a.task = "off_shift"
                yield self.env.timeout(600)
                return
            yield self.env.timeout(_IDLE_POLL_S)
            return
        route = min(ready, key=self.route_key)
        lab = self.config.labor
        route.status, route.picker = "picking", a.login
        route.pick_started_at = self.env.now
        pick_ids = [i for i in route.packages if self.pkgs[i].status == "stowed"]
        dur = (lab.pick_base_minutes * 60 + len(pick_ids) * lab.pick_seconds_per_package) / a.skill
        route.pick_eta = self.env.now + dur
        self._set_task(a, "picking", route.route_id, f"Aisle {route.aisle}")
        yield self.env.timeout(dur)
        a.busy_s += dur
        a.units += len(pick_ids)
        for i in pick_ids:
            pkg = self.pkgs[i]
            if pkg.missort and not pkg.missort_caught:
                pkg.status = "left_behind"
                continue
            pkg.status, pkg.picked_at = "picked", self.env.now
            route.picked_count += 1
            self.counters["picked"] += 1
        self.aisle_level[route.aisle] -= sum(
            1 for i in pick_ids if self.pkgs[i].location == route.aisle
        )
        route.picked_at = self.env.now
        route.status = "staging"
        o = self.config.outbound
        route.bags = max(1, math.ceil(max(1, route.picked_count) / o.packages_per_bag))
        route.carts = max(1, math.ceil(route.bags / o.bags_per_cart))
        hv = [i for i in route.packages if self.pkgs[i].hv and self.pkgs[i].status == "hv_in_cage"]
        route.hv_pending = len(hv)
        if hv:
            self.hv_q.put(("handoff", route.idx), hi=True)
        self._set_task(a, "staging", route.route_id, route.staging_location)
        for _ in range(route.carts):
            per = lab.stage_minutes_per_cart * 60 / a.skill
            yield self.env.timeout(per)
            a.busy_s += per
            route.carts_staged += 1
        for i in route.packages:
            if self.pkgs[i].status == "picked":
                self.pkgs[i].status, self.pkgs[i].staged_at = "staged", self.env.now
        self._maybe_staged(route)
        self._go_idle(a)

    def _maybe_staged(self, route: _Route) -> None:
        if (
            route.carts
            and route.carts_staged >= route.carts
            and route.hv_pending == 0
            and route.staged_at is None
        ):
            route.staged_at = self.env.now
            route.status = "staged"
            for i in route.packages:
                if self.pkgs[i].status == "picked":
                    self.pkgs[i].status, self.pkgs[i].staged_at = "staged", self.env.now
            ev = self._staged_events.get(route.idx)
            if ev is not None and not ev.triggered:
                ev.succeed()

    # --- dispatch -----------------------------------------------------------

    def planned_leave(self, d: _Driver) -> float:
        r = self.routes[d.route]
        arrive = r.planned_depart - self.config.dispatch.check_in_lead_minutes * 60
        return arrive - d.travel_s

    def _leave_time(self, d: _Driver) -> float:
        late = d.late_s
        if d.notified_at is not None and d.notified_at <= self.planned_leave(d) + d.late_s:
            late = d.late_s - d.recoverable_s
        return max(self.env.now, self.planned_leave(d) + late - d.early_s)

    def _traffic_delay(self, d: _Driver, at: float) -> float:
        sec = sector_of(*d.home)
        extra = 0.0
        for dis in self.disruptions_seen:
            if dis["kind"] == "traffic_incident" and dis.get("target") in (sec, None, "ALL"):
                if dis["from"] <= at < dis["to"]:
                    extra += dis["magnitude"] * 60
        return extra

    def _driver_proc(self, d: _Driver):
        while True:
            if d.state == "released":
                return
            leave = math.inf if d.no_show else self._leave_time(d)
            d.wake = self.env.event()
            if leave == math.inf:
                # No-show: the DSP sends a standby an hour past the check-in
                # deadline if nobody has acted sooner (the default DSP behaviour).
                d.state = "off_duty"
                r = self.routes[d.route]
                due = r.planned_depart - self.config.dispatch.check_in_lead_minutes * 60
                yield self.env.timeout(max(1.0, due + 3600 - self.env.now)) | d.wake
                if d.wake.triggered:
                    continue
                if d.state != "released" and r.driver == d.idx:
                    self.apply(
                        Intervention(kind="reassign_standby", target=r.route_id, source="dsp_auto")
                    )
                return
            if self.env.now < leave:
                d.state = "off_duty"
                yield self.env.timeout(leave - self.env.now) | d.wake
                if d.wake.triggered:
                    continue
            break
        if d.state == "released":
            return
        d.leave_at = self.env.now
        d.state = "en_route"
        d.extra_travel_s = self._traffic_delay(d, self.env.now)
        yield self.env.timeout(d.travel_s + d.extra_travel_s)
        if d.state == "released":
            return
        yield from self._check_in_and_go(d)

    def _check_in_and_go(self, d: _Driver):
        d.arrived_at = self.env.now
        d.state = "checked_in"
        route = self.routes[d.route]
        self.log("dispatch", f"{d.driver_id} ({d.dsp}) checked in for {route.route_id}")
        if route.staged_at is None:
            ev = self._staged_events.setdefault(route.idx, self.env.event())
            yield ev
        earliest = route.planned_depart - 15 * 60
        if self.env.now < earliest:
            yield self.env.timeout(earliest - self.env.now)
        d.state = "loading"
        route.status = "loading"
        yield self.env.timeout(self.config.dispatch.load_minutes * 60)
        self._depart(route, d)

    def _standby_proc(self, d: _Driver):
        d.leave_at = self.env.now
        d.state = "en_route"
        yield self.env.timeout(d.travel_s)
        yield from self._check_in_and_go(d)

    def _depart(self, route: _Route, d: _Driver) -> None:
        o, disp = self.config.outbound, self.config.dispatch
        now = self.env.now
        route.departed_at = d.departed_at = now
        route.status = "departed"
        d.state = "on_road"
        late_s = max(0.0, now - route.planned_depart)
        slack_s = (o.driver_window_hours - route.duration_hours) * 3600
        on_route = [i for i in route.packages if self.pkgs[i].status == "staged"]
        frac = max(0.0, (late_s - slack_s) / (route.duration_hours * 3600))
        route.not_attempted = min(len(on_route), math.ceil(frac * len(on_route)))
        n_att = len(on_route) - route.not_attempted
        per = route.duration_hours * 3600 / max(1, len(on_route))
        for k, i in enumerate(on_route):
            pkg = self.pkgs[i]
            pkg.status, pkg.departed_at = "on_road", now
            if k < n_att:
                pkg.attempt_at = now + (k + 0.5) * per
                pkg.attempted = True
                fail = disp.delivery_failure_rate * self._weather_factor(pkg.attempt_at)
                pkg.delivered = pkg.deliver_u >= fail
                route.failed += 0 if pkg.delivered else 1
            else:
                pkg.attempted, pkg.delivered = False, False
        d.return_at = now + route.duration_hours * 3600 + 20 * 60
        if not d.forget_swipe:
            d.swiped_at = d.return_at
        tol = disp.otd_tolerance_minutes * 60
        self.log(
            "dispatch",
            f"{route.route_id} departed "
            + ("on time" if late_s <= tol else f"{late_s / 60:.0f} min late"),
        )
        if all(r.departed_at is not None or r.sidelined for r in self.routes):
            self.departures_done = True
            self.env.process(self._end_of_day())

    def _end_of_day(self):
        last = max((d.return_at or 0) for d in self.drivers)
        yield self.env.timeout(max(0.0, min(last, DAY_END_MINUTE * 60) - self.env.now))
        self.day_complete = True

    # --- cycle --------------------------------------------------------------

    def _cycle_process(self):
        while self.env.now < self.cutoff:
            yield self.env.timeout(self.cutoff - self.env.now)
        self.pick_started = True
        self.log("cycle", f"Pick started for {self.config.cycle.name} — induct blocked")
        for pkg in self.pkgs:
            if pkg.status in ("pending_induct", "pending_stow", "problem_solve", "jackpot"):
                pkg.status = "rolled_over"
        for r in self.routes:
            if r.status == "not_ready":
                r.status = "ready"
        for a in self.assocs:
            if a.role in ("induct", "stow"):
                self.reassign(a, "pick")

    def _sampler(self):
        bucket = SERIES_BUCKET_MINUTES * 60
        last: Counter = Counter()
        while not self.day_complete:
            t = self.env.now
            if t % bucket == 0:
                s = self.series
                s["minute"].append(t / 60)
                for k in ("arrived", "inducted", "stowed", "picked"):
                    s[k].append(self.counters[k] - last[k])
                    last[k] = self.counters[k]
                s["wip_minutes"].append(round(self.wip_minutes(), 1))
                s["departed_routes"].append(
                    sum(1 for r in self.routes if r.departed_at is not None)
                )
                for role in ("induct", "stow", "pick", "problem_solve", "high_value"):
                    s[f"labor_{role}"].append(self.active(role) * SERIES_BUCKET_MINUTES / 60)
            if self.config.induct.start_minute * 60 <= t < self.cutoff and self.active("stow"):
                lo, hi = self.config.stow.wip_target_min, self.config.stow.wip_target_max
                self._wip_samples.append(lo <= self.wip_minutes() <= hi)
            yield self.env.timeout(WIP_SAMPLE_MINUTES * 60)

    def _scheduled(self, iv: Intervention):
        if self.env.now < iv.at_minute * 60:
            yield self.env.timeout(iv.at_minute * 60 - self.env.now)
        self.apply(iv)

    # --- levers / actions ---------------------------------------------------

    def reassign(self, a: _Assoc, role: str) -> None:
        if a.role == role:
            return
        a.role = role
        if role != "induct":
            a.line = None
        a.history.append((self.env.now / 60, role))

    def _take_associates(self, n: int, to_role: str, from_role: str) -> int:
        moved = 0
        for a in sorted(self.assocs, key=lambda x: x.skill):
            if moved >= n:
                break
            if a.present and a.role == from_role and a.task != "off_shift":
                self.reassign(a, to_role)
                moved += 1
        return moved

    def _call_vet(self, n: int, role: str) -> int:
        n = min(n, self.flex_remaining)
        lead = self.config.labor.vet_lead_minutes * 60
        for _ in range(n):
            self.flex_remaining -= 1
            start = self.env.now + lead
            if role == "pick":
                start = max(start, self.cutoff - 15 * 60)
            a = _Assoc(
                idx=len(self.assocs),
                login=f"flex{self._flex_rng.randrange(100, 999)}",
                home_role=role,
                role=role,
                skill=max(0.6, self._flex_rng.lognormvariate(-0.05, self.config.labor.skill_sigma)),
                present=True,
                shift_start=start,
                vet=True,
            )
            self.assocs.append(a)
            self.env.process(self._assoc_proc(a))
        return n

    def _disruption_iv(self, dis: Disruption) -> Intervention:
        return Intervention(
            kind="inject_disruption",
            at_minute=dis.at_minute,
            target=dis.target,
            amount=dis.magnitude,
            params=dis.model_dump(),
            source=f"disruption:{dis.source}",
        )

    def _wake_driver(self, d: _Driver) -> None:
        if d.wake is not None and not d.wake.triggered:
            d.wake.succeed()

    def route_by_id(self, target: str | None) -> _Route | None:
        return next((r for r in self.routes if r.route_id == target), None)

    def apply(self, iv: Intervention) -> dict:
        """Applies an action at the current sim time and returns what actually
        happened — a lever can be a no-op, and that is reported honestly."""
        handler = getattr(self, f"_act_{iv.kind}")
        effect = handler(iv, max(0, int(round(iv.amount))))
        now = self.env.now
        record = {
            "kind": iv.kind,
            "amount": iv.amount,
            "target": iv.target,
            "params": iv.params,
            "minute": now / 60,
            "clock": clock(now / 60),
            "source": iv.source,
            "effect": effect,
        }
        self.applied.append(record)
        self.log(
            "disruption" if iv.kind == "inject_disruption" else "action", effect, source=iv.source
        )
        return record

    def _act_add_stowers(self, iv, n):
        if self.env.now >= self.cutoff:
            return "no-op: stow window already closed"
        got = self._call_vet(n, "stow")
        if not got:
            return "no-op: flex pool exhausted"
        eta = clock((self.env.now + self.config.labor.vet_lead_minutes * 60) / 60)
        return f"VET: {got} flex associate(s) called in to stow, arriving {eta}"

    def _act_add_pickers(self, iv, n):
        if self.pick_started and not any(r.status == "ready" for r in self.routes):
            return "no-op: nothing left to pick"
        got = self._call_vet(n, "pick")
        return f"VET: {got} flex picker(s) called in" if got else "no-op: flex pool exhausted"

    def _act_open_induct_line(self, iv, n):
        if self.env.now >= self.cutoff:
            return "no-op: induct already blocked by pick start"
        if self.extra_lines >= MAX_SPARE_LINES:
            return f"no-op: all {MAX_SPARE_LINES} spare induct stations already open"
        donor = next(
            (
                a
                for a in sorted(self.assocs, key=lambda x: -x.skill)
                if a.present and a.role == "stow" and a.task != "off_shift"
            ),
            None,
        )
        if donor is None:
            return "no-op: no associate available to staff a spare line"
        self.extra_lines += 1
        self.reassign(donor, "induct")
        donor.line = self.total_lines()
        return f"spare induct line L{donor.line} opened, staffed by {donor.login} (from stow)"

    def _act_extend_cutoff(self, iv, n):
        room = MAX_CUTOFF_EXTENSION_MINUTES - self.cutoff_extension_minutes
        minutes = max(0.0, min(iv.amount, room))
        if self.env.now >= self.cutoff or minutes == 0:
            return "no-op: pick already started or extension cap reached"
        self.cutoff += minutes * 60
        self.cutoff_extension_minutes += minutes
        for a in self.assocs:
            if a.home_role == "pick" and not a.vet and a.task == "off_shift":
                a.shift_start = max(a.shift_start, self.cutoff - 15 * 60)
        return f"pick start moved to {clock(self.cutoff / 60)} (+{minutes:.0f} min)"

    def _act_priority_late_linehauls(self, iv, n):
        self.priority_late = True
        moved = self.induct_q.promote(
            lambda idx: (
                self.pkgs[idx].trip >= 0
                and self.config.linehauls[self.pkgs[idx].trip].delay_minutes > 0
            )
        )
        return (
            f"late-linehaul volume prioritised at yard and induct ({moved} queued packages moved)"
        )

    def _act_move_associates(self, iv, n):
        fr = iv.params.get("from_role", "problem_solve")
        to = iv.target or iv.params.get("to_role", "stow")
        if to in ("induct",):
            return "no-op: use open_induct_line to staff an induct line"
        got = self._take_associates(n, to, fr)
        return (
            f"moved {got} associate(s) {fr} → {to}"
            if got
            else f"no-op: no available {fr} associates"
        )

    def _act_resequence_unload(self, iv, n):
        t = next((i for i, p in enumerate(self.config.linehauls) if p.trip_id == iv.target), None)
        if t is None or self.trips[t].status not in ("in_transit", "in_yard"):
            return "no-op: trip not waiting for a door"
        self.trips[t].priority += 10
        return f"{iv.target} moved to the front of the unload sequence"

    def _act_prioritize_route(self, iv, n):
        r = self.route_by_id(iv.target)
        if r is None or r.status not in ("not_ready", "ready"):
            return "no-op: route already picked or unknown"
        r.priority += max(1, n)
        return f"{r.route_id} prioritised for pick (priority {r.priority})"

    def _act_sideline_route(self, iv, n):
        r = self.route_by_id(iv.target)
        if r is None or r.status not in ("not_ready", "ready"):
            return "no-op: route already picked or unknown"
        r.sidelined = True
        return f"{r.route_id} sidelined (held out of pick)"

    def _act_unsideline_route(self, iv, n):
        r = self.route_by_id(iv.target)
        if r is None or not r.sidelined:
            return "no-op: route not sidelined"
        r.sidelined = False
        return f"{r.route_id} returned to pick"

    def _act_move_route_wave(self, iv, n):
        r = self.route_by_id(iv.target)
        waves = self.config.outbound.wave_stage_by_minutes
        if r is None or r.departed_at is not None or r.status == "loading":
            return "no-op: route departed/loading or unknown"
        step = max(1, n)
        new_w = min(len(waves) - 1, r.wave + step)
        shift = (waves[new_w] - waves[r.wave]) * 60 if new_w != r.wave else 20 * 60 * step
        r.wave = new_w
        r.stage_by += shift
        r.planned_depart += shift
        r.moved_waves += 1
        if r.driver is not None:
            d = self.drivers[r.driver]
            d.notified_at = d.notified_at or self.env.now
            self._wake_driver(d)
        return (
            f"{r.route_id} moved to stage-by {clock(r.stage_by / 60)}, depart "
            f"{clock(r.planned_depart / 60)}; DSP and driver notified"
        )

    def _act_notify_drivers(self, iv, n):
        early = float((iv.params or {}).get("leave_early_minutes", 0)) * 60
        sector = (iv.params or {}).get("sector")
        routes = (iv.params or {}).get("routes")
        if routes:
            targets = [
                self.drivers[r.driver]
                for r in self.routes
                if r.route_id in set(routes)
                and r.driver is not None
                and self.drivers[r.driver].state in ("off_duty", "en_route")
            ]
        elif sector:
            targets = [
                d
                for d in self.drivers
                if d.state == "off_duty"
                and d.leave_at is None
                and sector_of(*d.home) == sector
                and not d.no_show
            ]
        else:
            targets = self.driver_targets(iv.target)
        for d in targets:
            if d.notified_at is None:
                d.notified_at = self.env.now
            if early:
                d.early_s = max(d.early_s, early)
            self._wake_driver(d)
        if early:
            return (
                f"told {len(targets)} driver(s) in sector {sector} to leave "
                f"{early / 60:.0f} min early (traffic incident)"
            )
        return f"notified {len(targets)} driver(s) of their wave and check-in time"

    def _act_reassign_standby(self, iv, n):
        r = self.route_by_id(iv.target)
        now = self.env.now
        if r is None or r.departed_at is not None:
            return "no-op: route departed or unknown"
        if self.standby_remaining.get(r.dsp, 0) <= 0:
            return f"no-op: {r.dsp} has no standby driver left"
        old = self.drivers[r.driver]
        if old.state in ("checked_in", "loading"):
            return "no-op: assigned driver already checked in"
        self.standby_remaining[r.dsp] -= 1
        old.state = "released"
        self._wake_driver(old)
        rng = random.Random(f"standby:{self.config.seed}:{r.idx}:{int(now)}")
        lead = self.config.dispatch.standby_lead_minutes * 60
        new = _Driver(
            idx=len(self.drivers),
            driver_id=f"DRV-{rng_hex(rng, 2)}",
            dsp=r.dsp,
            route=r.idx,
            home=(rng.uniform(-3, 3), rng.uniform(-3, 3)),
            travel_s=lead,
            late_s=0.0,
            recoverable_s=0.0,
            no_show=False,
            forget_swipe=rng.random() < self.config.dispatch.swipe_forget_rate,
            standby=True,
            notified_at=now,
        )
        self.drivers.append(new)
        r.driver = new.idx
        self.env.process(self._standby_proc(new))
        eta = clock((now + lead) / 60)
        return f"{r.dsp} standby {new.driver_id} assigned to {r.route_id}, ETA {eta}"

    def _act_notify_swipe_finish(self, iv, n):
        now = self.env.now
        pending = [
            d for d in self.drivers if d.return_at and d.return_at <= now and d.swiped_at is None
        ]
        for d in pending:
            d.swiped_at = now + 5 * 60
            d.swipe_notified = True
        return f"{len(pending)} returned driver(s) reminded to swipe to finish"

    def _act_start_scrub(self, iv, n):
        kind = iv.target or "in_station"
        found = 0
        for b in self.backlog:
            if b["resolution"]:
                continue
            u = random.Random(f"scrub:{b['tracking_id']}").random()
            if kind == "in_station" and b["status"] == "marked_missing" and u < 0.6:
                b["resolution"] = "found_in_station"
                found += 1
            elif kind == "on_road" and b["status"] == "on_road":
                b["resolution"] = "confirmed_delivered" if u < 0.7 else "marked_missing"
                found += 1
        self.scrubs.append({"kind": kind, "minute": self.env.now / 60, "resolved": found})
        return f"{kind.replace('_', '-')} scrub: {found} package(s) resolved"

    def _act_inject_disruption(self, iv, n):
        p = iv.params or {}
        kind = p.get("kind", iv.target)
        now = self.env.now
        dur = float(p.get("duration_minutes") or 30) * 60
        mag = float(p.get("magnitude", iv.amount))
        target = p.get("target", iv.target if iv.target != kind else None)
        self.disruptions_seen.append(
            {
                "kind": kind,
                "from": now,
                "to": now + dur,
                "magnitude": mag,
                "target": target,
                "clock": clock(now / 60),
                "source": iv.source,
            }
        )
        if kind == "line_jam":
            line = int(target or 1)
            self.line_down_windows.append((line, now, now + dur, "jam"))
            return f"Induct line L{line} jammed for {dur / 60:.0f} min"
        if kind == "scanner_degradation":
            line = int(target or 1)
            self.scanner_mult.append((line, now, now + dur, mag))
            return f"Scanner on L{line} degraded (no-read x{mag:g}) for {dur / 60:.0f} min"
        if kind == "absenteeism":
            role = target or "stow"
            gone = 0
            for a in sorted(self.assocs, key=lambda x: -x.idx):
                if gone >= int(mag):
                    break
                if a.present and a.role == role:
                    a.present, a.role = False, "off"
                    gone += 1
            return f"{gone} {role} associate(s) left the shift"
        if kind == "traffic_incident":
            for d in self.drivers:
                if d.state == "en_route" and sector_of(*d.home) == (target or sector_of(*d.home)):
                    d.extra_travel_s += mag * 60  # already-driving drivers are slowed too
            return f"Traffic incident in sector {target or 'ALL'}: +{mag:.0f} min travel"
        if kind == "weather":
            self.weather_mult.append((now, mag))
            return f"Weather: delivery-failure risk x{mag:g} from {clock(now / 60)}"
        if kind == "volume_surge":
            rng = random.Random(f"surge:{self.config.seed}:{int(now)}")
            ids = [self._new_pkg(rng, -1, manifested=False).idx for _ in range(int(mag))]
            for i in ids:
                self._receive(i)
            return f"Unplanned volume surge: {len(ids)} unmanifested packages arrived"
        return f"unknown disruption {kind}"

    def driver_targets(self, target: str | None) -> list[_Driver]:
        live = [d for d in self.drivers if d.state in ("off_duty", "en_route") and not d.standby]
        if target in (None, "late", "at_risk"):
            return [d for d in live if d.late_s > 0 or d.no_show or self.driver_late_by(d) > 0]
        if target == "all":
            return live
        r = self.route_by_id(target)
        return [self.drivers[r.driver]] if r and r.driver is not None else []

    def driver_expected_checkin(self, d: _Driver) -> float:
        """What dispatch can see: planned check-in, or (once the driver has left)
        the live ETA. A driver who should have left but hasn't is projected
        to leave now."""
        if d.arrived_at is not None:
            return d.arrived_at
        if d.leave_at is not None:
            return d.leave_at + d.travel_s + d.extra_travel_s
        leave = max(self.planned_leave(d), self.env.now)
        return leave + d.travel_s

    def driver_late_by(self, d: _Driver) -> float:
        r = self.routes[d.route]
        due = r.planned_depart - self.config.dispatch.check_in_lead_minutes * 60
        return max(0.0, self.driver_expected_checkin(d) - due) / 60

    # --- stepping / measures -------------------------------------------------

    @property
    def done(self) -> bool:
        """Departures complete — what DEA/OTD/staging outcomes depend on."""
        return self.departures_done

    def run_until(self, minute: float) -> None:
        target = minute * 60
        if target > self.env.now:
            self.env.run(until=target)

    def run_to_end(self, max_minute: float = 1440) -> None:
        while not self.departures_done and self.env.now < max_minute * 60:
            self.run_until(self.env.now / 60 + 15)

    @property
    def now_minute(self) -> float:
        return self.env.now / 60

    def total_stow_rate_per_min(self) -> float:
        stowers = self.active("stow") or self.config.stow.stowers
        return max(1, stowers) * self.config.stow.rate_pph_per_stower / 60

    def wip_minutes(self) -> float:
        return len(self.stow_q) / self.total_stow_rate_per_min()

    def rate_last_hour(self, times: list[float]) -> int:
        lo = self.env.now - 3600
        n = 0
        for t in reversed(times):
            if t < lo:
                break
            n += 1
        return n
