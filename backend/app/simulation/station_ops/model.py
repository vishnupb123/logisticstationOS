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
import zlib
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
    "restage_cart",
    "direct_sweep",
    "request_replacement_van",
    "add_yard_marshal",
    "check_ferry",
    "draft_gtdr",
    "replan_next_day",
    "offer_vet",
    "offer_vto",
    # v2 (HANDOFF_V2 E2/E3/E4/E5/E7/E8)
    "force_induct",
    "change_cycle",
    "enable_cycle",
    "rebalance_finger",
    "approve_damaged",
    "watch_trip",
    "post_opportunity",
    "close_window",
    "rerun_rotation",
]


def _u(*keys) -> float:
    """Deterministic uniform [0, 1) from keys (independent of draw order)."""
    h = zlib.crc32(":".join(map(str, keys)).encode())
    h = (h * 2654435761) & 0xFFFFFFFF
    return h / 4294967296


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
    #: Why a package was left on the floor (missort / bag_not_loaded).
    left_reason: str | None = None
    #: How a left-behind package was recovered (sweep_staged / cluster_transfer).
    recovered: str | None = None
    # --- v2 ---------------------------------------------------------------------
    #: In the upstream container plan (planned) vs. not (unplanned).
    planned: bool = True
    #: CYCLE_1 / High_Value / UNPLANNED (until assigned at induct by the dynamic plan).
    cycle: str = "CYCLE_1"
    container: int = -1
    conveyable: bool = True
    missed_induct: bool = False
    stower_err: bool = False
    spot_u: float = 1.0
    stop_u: float = 1.0
    buffer_s: float = 900.0
    #: Problem-solve state machine (damaged / misdivert / missed induct).
    ps_state: str | None = None
    misdivert_kind: str | None = None
    finger: str | None = None
    inducted_by: str | None = None
    stowed_by: str | None = None
    approval_at: float | None = None


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
    home_line: int | None = None
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
    # --- v2 per-path performance ---------------------------------------------------
    fsaf: int = 0
    stow_to_ps: int = 0
    spot_checks: int = 0
    spot_defects: int = 0
    picklists: int = 0
    picklist_id: str | None = None
    path_hours: dict = field(default_factory=dict)


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
    # floor exceptions (pre-drawn; revealed only when they happen)
    misstage: bool = False
    misstage_notice_s: float = 0.0
    forget_bag: bool = False
    misstaged_at: str | None = None
    misstaged_by: str | None = None
    misstaged_since: float | None = None
    misstage_fixed_at: float | None = None
    restaging: bool = False
    restage_ev: object = None
    forgotten: int = 0


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
    # vehicle safety audit (VSA) at check-in — pre-drawn per van
    vsa_u: float = 1.0
    vsa_fix_s: float = 0.0
    vsa_defect: str | None = None
    vsa_result: str | None = None
    vsa_at: float | None = None
    vsa_wait_s: float = 0.0
    grounded_at: float | None = None
    van_request: str | None = None
    van_eta: float | None = None
    van_event: object = None


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
    if day < 0:
        return f"D{day} {label}"
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
        self.notifications: list[dict] = []
        self._nid = 0
        #: Set when something sudden happens; the runtime wakes the agents early.
        self.urgent = False
        self.swept: dict[str, float] = {}
        #: aisle -> last time a route there finished picking (sweep is due after it)
        self.sweep_due: dict[str, float] = {}
        self.sweeping: set[str] = set()
        self.sweep_priority: list[str] = []
        self.sweep_passes: Counter = Counter()
        self.sweep_log: list[dict] = []
        self._marshal_free = [0.0] * c.dispatch.yard_marshals
        self.extra_marshals = 0
        self.spare_vans = {d.code: d.spare_vans for d in c.dispatch.dsps}
        self.departures_done_at: float | None = None
        # --- v2 state -------------------------------------------------------------
        #: per induct line: last scan time, lost seconds (documented belt-gap rule), stops
        self._last_scan: dict[int, float] = {}
        self.gap_lost_s: Counter = Counter()
        self.gap_stops: Counter = Counter()
        self._line_scan_times: dict[int, list[float]] = defaultdict(list)
        self.n_buffered = 0
        self.finger_stats: dict[str, Counter] = defaultdict(Counter)
        self.finger_rebalanced: dict[str, float] = {}
        self.force_until: float | None = None
        self.next_cycle_until: float | None = None
        self.cycle_changes: list[dict] = []
        self.network_missorts: list[dict] = []
        self.wip_intervals: list[dict] = []
        self.watch: set[str] = set()
        self.approve_fast = False
        from app.simulation.station_ops.work_items import WorkItemStore

        self.work_items = WorkItemStore(self)

        self._build_routes()
        self._build_packages()
        self._build_associates()
        self._build_drivers()
        self._build_backlog()
        self._build_floor()
        self._build_containers()
        self.trips = [_Trip(i) for i in range(len(c.linehauls))]
        self.aisle_level: Counter = Counter()
        self.aisle_capacity = self._aisle_capacity()

        self.induct_q = _Queue(self.env)
        self.stow_q = _Queue(self.env)
        self.problem_q = _Queue(self.env)
        self.hv_q = _Queue(self.env)
        self.noncon_q = _Queue(self.env)
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
        self.env.process(self._drain_end())
        self.env.process(self._sampler())
        from app.simulation.station_ops.closeout import Closeout

        self.closeout = Closeout(self)
        for p in self._carryover_ids:
            self.env.process(self._carryover_arrival(p))
        for item in c.carried_work_items:
            self.work_items.carry(item)
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
        key = (self.config.seed, pkg.tracking_id)
        ic, sc = self.config.induct, self.config.stow
        pkg.conveyable = _u("conv", *key) < ic.conveyable_share
        pkg.missed_induct = _u("missed", *key) < ic.missed_induct_rate
        pkg.stower_err = _u("stower", *key) < sc.stower_error_rate
        pkg.spot_u = _u("spot", *key)
        pkg.stop_u = _u("stop", *key)
        lo, hi = self.config.sort.stow_buffer_minutes
        pkg.buffer_s = (lo + (hi - lo) * _u("buf", *key)) * 60
        if trip >= 0:
            pkg.planned = _u("plan", *key) >= self.config.linehauls[trip].unplanned_share
        else:
            pkg.planned = carryover
        if manifested is False and not carryover:
            pkg.planned = False
        pkg.cycle = (
            (self.config.cycle.high_value_cycle if pkg.hv else self.config.cycle.name)
            if pkg.planned
            else "UNPLANNED"
        )
        self.pkgs.append(pkg)
        self.routes[pkg.route].packages.append(pkg.idx)
        return pkg

    def _build_containers(self) -> None:
        """Gaylords and pallets per linehaul (synthetic ids), unloaded and
        inducted container by container."""
        rng = random.Random(f"containers:{self.config.seed}")
        self.containers: list[dict] = []
        self.trip_containers: list[list[int]] = []
        for t_idx, ids in enumerate(self.trip_pkgs):
            mine: list[int] = []
            k = 0
            while k < len(ids):
                kind = "GAYLORD" if rng.random() < 0.72 else "PALLET"
                size = rng.randint(250, 450) if kind == "GAYLORD" else rng.randint(90, 150)
                chunk = ids[k : k + size]
                cid = len(self.containers)
                self.containers.append(
                    {
                        "id": f"{kind}_{rng_hex(rng, 3)}",
                        "type": kind,
                        "trip": t_idx,
                        "pkgs": chunk,
                        "unloaded_at": None,
                    }
                )
                for i in chunk:
                    self.pkgs[i].container = cid
                mine.append(cid)
                k += size
            self.trip_containers.append(mine)

    # --- break schedule / belt run time (documented formula) ---------------------

    def in_break(self, t: float | None = None) -> tuple[float, str] | None:
        t = self.env.now if t is None else t
        for b in self.config.settings.breaks:
            if b.start_minute * 60 <= t < (b.start_minute + b.minutes) * 60:
                return (b.start_minute + b.minutes) * 60, b.label
        return None

    def belt_run_minutes(self, start: float, end: float) -> float:
        """Belt run time in [start, end] minutes: sort window minus fast start,
        breaks and lunch (documented: sort end − sort start − (fast start +
        breaks + lunch))."""
        st = self.config.settings
        s0 = self.config.induct.start_minute
        start = max(start, s0)
        if end <= start:
            return 0.0
        run = end - start
        fast_end = s0 + st.fast_start_minutes
        run -= max(0.0, min(end, fast_end) - start)
        for b in st.breaks:
            run -= max(0.0, min(end, b.start_minute + b.minutes) - max(start, b.start_minute))
        return max(0.0, run)

    def is_automated(self, line: int) -> bool:
        return 1 <= line <= self.config.induct.automated_lines

    def line_rate(self, line: int) -> float:
        ic = self.config.induct
        return ic.automated_rate_pph if self.is_automated(line) else ic.rate_pph_per_line

    def line_name(self, line: int) -> str:
        return f"AUTO-{line}" if self.is_automated(line) else f"L{line}"

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
                a.line = a.home_line = line
                line += 1
            self.assocs.append(a)
        # an absent inductor's line is covered by a present stower
        for a in self.assocs:
            if a.role == "induct" and not a.present:
                sub = next((b for b in self.assocs if b.role == "stow" and b.present), None)
                if sub:
                    sub.role, sub.home_role, sub.line = "induct", "induct", a.line
                    sub.home_line = a.line
                a.line = None
        self._flex_rng = random.Random(f"flex:{c.seed}")

    def _build_drivers(self) -> None:
        c, d = self.config, self.config.dispatch
        rng = random.Random(f"drivers:{c.driver_seed or c.seed}")
        late_rate = {x.code: x.late_rate for x in d.dsps}
        vrng = random.Random(f"vsa:{c.driver_seed or c.seed}")
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
            self._draw_vsa(drv, vrng)
            for key, value in c.driver_overrides.get(r.idx, {}).items():
                setattr(drv, key, value)
            r.driver = drv.idx
            r.stops = math.ceil(len(r.packages) / 1.15) if r.packages else 0
            self.drivers.append(drv)

    _MINOR = ("tyre pressure low", "wiper blade torn", "mirror loose", "washer fluid empty")
    _CRITICAL = ("brake warning light", "tyre sidewall damage", "windscreen crack", "fluid leak")

    def _draw_vsa(self, drv: "_Driver", rng: random.Random) -> None:
        drv.vsa_u = rng.random()
        drv.vsa_fix_s = rng.uniform(5, 14) * 60
        d = self.config.dispatch
        if drv.vsa_u < d.vsa_ground_rate:
            drv.vsa_defect = rng.choice(self._CRITICAL)
        elif drv.vsa_u < d.vsa_ground_rate + d.vsa_minor_rate:
            drv.vsa_defect = rng.choice(self._MINOR)
        else:
            rng.random()

    def _build_floor(self) -> None:
        """Pre-draws per-route floor behaviour: a cart scanned into the wrong
        staging location, a bag left in the aisle. Unknown until it happens."""
        c, o = self.config, self.config.outbound
        rng = random.Random(f"floor:{c.driver_seed or c.seed}")
        lo, hi = o.misstage_notice_minutes
        for r in self.routes:
            r.misstage = rng.random() < o.misstage_rate
            r.misstage_notice_s = rng.uniform(lo, hi) * 60
            r.forget_bag = rng.random() < o.bag_forget_rate
            for key, value in c.route_overrides.get(r.idx, {}).items():
                setattr(r, key, value)

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

    def notify(
        self, audience: str, kind: str, severity: str, title: str, message: str, **refs
    ) -> dict:
        """A message to the supervisor / manager / a DSP / a driver. In the
        twin this is a record shown in the UI — nobody real is contacted."""
        self._nid += 1
        n = {
            "id": self._nid,
            "minute": round(self.env.now / 60, 2),
            "clock": clock(self.env.now / 60),
            "audience": audience,
            "kind": kind,
            "severity": severity,
            "title": title,
            "message": message,
            "ack": False,
            "acked_at": None,
            **refs,
        }
        from app.simulation.station_ops.work_items import KIND_MAP

        if audience in ("supervisor", "manager") and (
            severity in ("warning", "critical") or kind in KIND_MAP
        ):
            ref = (
                refs.get("route_id")
                or refs.get("aisle")
                or refs.get("driver_id")
                or refs.get("ref")
            )
            wi = self.work_items.add(
                kind=kind,
                title=title,
                owner=audience,
                started_by="system",
                ref=ref,
                priority=1 if severity == "critical" else None,
                source_ref={"notification": self._nid},
            )
            n["work_item"] = wi["id"]
        self.notifications.append(n)
        if len(self.notifications) > 600:
            self.notifications = self.notifications[-500:]
        if severity in ("critical", "warning") and audience in ("supervisor", "manager"):
            self.urgent = True
        return n

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
        arrive = (plan.planned_arrival_minute + plan.delay_minutes) * 60
        yield self.env.timeout(max(0.0, arrive))
        trip.status = "in_yard"
        # trailers that landed the evening before keep their real arrival time
        trip.yard_at = arrive if arrive < 0 else self.env.now
        self.yard.append(t)
        self.log("inbound", f"{plan.trip_id} ({plan.origin}) arrived in yard")
        if not self._door_wake.triggered:
            self._door_wake.succeed()

    def _yard_key(self, t: int):
        plan = self.config.linehauls[t]
        late = plan.delay_minutes > 0 and self.priority_late
        return (-self.trips[t].priority, not late, self.trips[t].yard_at, t)

    def _dock_process(self):
        open_at = (self.config.induct.start_minute - self.config.unload_lead_minutes) * 60
        if self.env.now < open_at:
            yield self.env.timeout(open_at - self.env.now)
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
        per_pkg = self.config.unload_minutes_per_1000 * 60 / 1000
        sc = self.config.sort
        for cid in self.trip_containers[t]:
            cont = self.containers[cid]
            yield self.env.timeout(len(cont["pkgs"]) * per_pkg)
            cont["unloaded_at"] = self.env.now
            for idx in cont["pkgs"]:
                self._receive(idx, hi=self.priority_late and plan.delay_minutes > 0)
            # network missorts arrive mixed into the container (not our packages)
            n = int(len(cont["pkgs"]) * sc.network_missort_rate + _u("nm", self.config.seed, cid))
            for k in range(n):
                rec = {
                    "id": f"NM-{cid:04d}{k}",
                    "reason": "wrong_station" if _u("nmr", cid, k) < 0.7 else "wrong_carrier",
                    "trip": plan.trip_id,
                    "container": cont["id"],
                    "status": "pending_ps",
                    "sidelined_at": self.env.now,
                    "replanned_at": None,
                    "resolved_at": None,
                }
                self.network_missorts.append(rec)
                self.problem_q.put(("network", len(self.network_missorts) - 1))
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
        if self.pick_started and not self._forcing():
            pkg.status = "next_cycle" if self._next_cycle_open() else "rolled_over"
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
        while not self.departures_done or (
            a.present and a.role == "problem_solve" and self._sweep_open()
        ):
            if not a.present or a.role == "off":
                a.task = "off_shift"
                yield self.env.timeout(600)
                continue
            role = a.role
            if role in ("induct", "stow", "problem_solve") and not self.pick_started:
                brk = self.in_break()
                if brk:
                    self._set_task(a, brk[1], None, None)
                    yield self.env.timeout(max(1.0, brk[0] - self.env.now))
                    continue
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
            elif role == "yard_marshal":
                self._set_task(a, "vsa_checks", None, "Yard")
                yield self.env.timeout(_IDLE_POLL_S)
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

    def _forcing(self) -> bool:
        return self.force_until is not None and self.env.now < self.force_until

    def _next_cycle_open(self) -> bool:
        return self.next_cycle_until is not None and self.env.now < self.next_cycle_until

    def _induct_task(self, a: _Assoc):
        if self.pick_started and not (self._forcing() and a.home_role == "induct"):
            self.reassign(a, "pick")
            yield self.env.timeout(0)
            return
        line = a.line or 1
        fast_end = (self.config.induct.start_minute + self.config.settings.fast_start_minutes) * 60
        if self.env.now < fast_end:
            self._set_task(a, "fast_start", f"L{line}", f"Induct {self.line_name(line)}")
            yield self.env.timeout(fast_end - self.env.now)
            return
        if self.line_down(line):
            self._set_task(a, "line_down", f"L{line}", f"Induct {self.line_name(line)}")
            yield self.env.timeout(
                max(
                    1.0,
                    min(self._line_up_at(line), max(self.cutoff, self.force_until or 0))
                    - self.env.now,
                )
            )
            return
        auto = self.is_automated(line)
        if not auto and len(self.noncon_q):
            idx = yield from self._wait_get(self.noncon_q, a, 1)
        else:
            limit = self._until_cutoff() if not self._forcing() else _IDLE_POLL_S
            idx = yield from self._wait_get(self.induct_q, a, limit)
        if idx is None:
            return
        pkg = self.pkgs[idx]
        if pkg.status != "pending_induct":
            return
        if auto and not pkg.conveyable:
            # non-conveyable: pulled off the automated line to manual handling
            self.counters["noncon"] += 1
            self.noncon_q.put(idx)
            yield self.env.timeout(2)
            return
        pkg.status = "inducting"
        self._set_task(a, "inducting", pkg.tracking_id, f"Induct {self.line_name(line)}")
        ic = self.config.induct
        dur = 3600 / self.line_rate(line) / a.skill * pkg.induct_mult
        if not pkg.manifested:
            dur += 10
        # micro-stop (jam clearing, label issue): the documented belt-gap defect
        stop_p = 0.004 * self._scanner_factor(line)
        if pkg.stop_u < stop_p:
            dur += 20 + 100 * (pkg.stop_u / stop_p)
        yield self.env.timeout(dur)
        a.busy_s += dur
        a.units += 1
        self._scan(line)
        pkg.line = line
        pkg.inducted_by = a.login
        self.counters["induct_attempts"] += 1
        self.line_stats[line]["attempts"] += 1
        if pkg.missed_induct and not pkg.reworked:
            # carried past the scanner without a scan — sits on the floor until
            # dwell / problem solve finds it (documented "missed induct")
            pkg.status, pkg.ps_state = "missed_induct", "missed_induct"
            self.counters["missed_induct"] += 1
            self.line_stats[line]["missed_induct"] += 1
            self.env.process(self._missed_found(idx))
            self._go_idle(a)
            return
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
                if auto and defect in ("no_read", "multi_read"):
                    self.finger_stats[self._finger(pkg)]["no_read"] += 1
                pkg.status, pkg.problem = "problem_solve", defect
                pkg.ps_state = "pending_ps"
                self.problem_q.put(("pkg", idx))
                self._go_idle(a)
                return
        self._inducted(pkg, line)
        self._go_idle(a)

    def _scan(self, line: int) -> None:
        """Belt-gap accounting (documented): a gap between consecutive packages
        on one belt of 20–120 s is a downtime defect; lost hours sum them."""
        now = self.env.now
        lo, hi = self.config.settings.belt_gap_defect_seconds
        last = self._last_scan.get(line)
        start = (self.config.induct.start_minute + self.config.settings.fast_start_minutes) * 60
        if last is not None and last >= start:
            gap = now - last
            if lo < gap < hi:
                self.gap_lost_s[line] += gap
                self.gap_stops[line] += 1
        self._last_scan[line] = now
        self._line_scan_times[line].append(now)

    def _missed_found(self, idx: int):
        dwell = self.config.settings.induct_dwell_minutes
        yield self.env.timeout((dwell + 15 + 30 * _u("mf", idx)) * 60)
        pkg = self.pkgs[idx]
        if pkg.status != "missed_induct":
            return
        if self.pick_started and not self._forcing():
            pkg.status = "rolled_over"
            return
        pkg.status, pkg.problem = "problem_solve", "missed_induct"
        self.problem_q.put(("pkg", idx))

    def _finger(self, pkg: _Pkg) -> str:
        cluster = self.routes[pkg.route].cluster
        return self.finger_rebalanced.get(cluster, f"FINGER-{cluster}")

    def _inducted(self, pkg: _Pkg, line: int) -> None:
        pkg.inducted_at = self.env.now
        if pkg.cycle == "UNPLANNED":
            pkg.cycle = self.config.cycle.name  # dynamic plan assigns the cycle at induct
            self.counters["unplanned_inducted"] += 1
        if self.pick_started and not self._forcing():
            pkg.status = "rolled_over"
            return
        self.counters["inducted"] += 1
        self.counters["inducted_auto" if self.is_automated(line) else "inducted_manual"] += 1
        self.line_stats[line]["inducted"] += 1
        self._inducted_times.append(self.env.now)
        if pkg.hv:
            pkg.status = "hv_pending_scan_in"
            self.hv_q.put(("scan_in", pkg.idx))
            return
        self.counters["sorted"] += 1
        if pkg.missort:
            self.counters["missorts"] += 1
            pkg.misdivert_kind = "auto_divert" if self.is_automated(line) else "wrong_rack"
        route = self.routes[pkg.route]
        if self.pick_started and route.status not in ("not_ready", "ready"):
            self._late_to_route(pkg)
            return
        if self.is_automated(line):
            finger = self._finger(pkg)
            pkg.finger = finger
            fs = self.finger_stats[finger]
            fs["volume"] += 1
            if fs["buffer"] >= self.config.sort.finger_bay_capacity:
                # bays full: the finger diverts to the jackpot
                fs["full_bay"] += 1
                fs["jackpot"] += 1
                pkg.status = "jackpot"
                self.counters["jackpot"] += 1
                self.counters["full_bay"] += 1
                self.cluster_stats[route.cluster]["jackpot"] += 1
                self.problem_q.put(("jackpot", pkg.idx))
                return
            fs["buffer"] += 1
        pkg.status = "stow_buffered"
        self.n_buffered += 1
        self.env.process(self._buffer(pkg))

    def _buffer(self, pkg: _Pkg):
        yield self.env.timeout(pkg.buffer_s)
        if pkg.status != "stow_buffered":
            return  # the drain closed first (already rolled over and un-counted)
        self.n_buffered -= 1
        if pkg.finger:
            self.finger_stats[pkg.finger]["buffer"] -= 1
        pkg.status = "pending_stow"
        self.stow_q.put(pkg.idx)

    def _late_to_route(self, pkg: _Pkg) -> None:
        """Force-inducted after pick start: straight to the route's cart if the
        van hasn't left, otherwise into tomorrow's cycle."""
        route = self.routes[pkg.route]
        if route.departed_at is None and route.status in ("staging", "staged", "picking"):
            pkg.status, pkg.staged_at, pkg.picked_at = "staged", self.env.now, self.env.now
            route.picked_count += 1
            self.counters["force_staged"] += 1
        else:
            pkg.status = "next_cycle"
            self.counters["next_cycle"] += 1

    def _stow_draining(self) -> bool:
        drain = self.config.stow.drain_minutes * 60
        return self.env.now < self.cutoff + drain and (len(self.stow_q) > 0 or self.n_buffered > 0)

    def _stow_task(self, a: _Assoc):
        if self.pick_started and not self._stow_draining():
            self.reassign(a, "pick")
            yield self.env.timeout(0)
            return
        idx = yield from self._wait_get(
            self.stow_q, a, self._until_cutoff() if not self.pick_started else 60
        )
        if idx is None:
            return
        pkg = self.pkgs[idx]
        route = self.routes[pkg.route]
        pkg.status = "stowing"
        self._set_task(a, "stowing", pkg.tracking_id, f"Aisle {route.aisle}")
        dur = 3600 / self.config.stow.rate_pph_per_stower / a.skill * pkg.stow_mult
        yield self.env.timeout(dur)
        a.busy_s += dur
        a.units += 1
        if pkg.missort and pkg.missort_caught and not pkg.reworked:
            # stow scan says wrong aisle cluster → problem solve → re-induct
            a.stow_to_ps += 1
            self.counters["stow_to_ps"] += 1
            pkg.status, pkg.problem, pkg.ps_state = "problem_solve", "misdivert", "misdivert"
            self.problem_q.put(("pkg", idx))
            self._go_idle(a)
            return
        if self.pick_started and route.status not in ("not_ready", "ready"):
            self._late_to_route(pkg)
            self._go_idle(a)
            return
        if self.aisle_level[route.aisle] >= self.aisle_capacity.get(route.aisle, 10**9):
            pkg.status = "jackpot"
            self.counters["jackpot"] += 1
            self.cluster_stats[route.cluster]["jackpot"] += 1
            self.problem_q.put(("jackpot", idx))
        else:
            pkg.stowed_by = a.login
            if pkg.stower_err and not pkg.missort:
                # stower put it on the wrong rack: a first-sort-attempt failure
                pkg.missort, pkg.missort_caught = True, False
                pkg.misdivert_kind = "stower"
                a.fsaf += 1
                self.counters["stower_fsaf"] += 1
            if pkg.spot_u < self.config.stow.spot_check_rate:
                a.spot_checks += 1
                self.counters["spot_checks"] += 1
                if pkg.missort and not pkg.missort_caught:
                    a.spot_defects += 1
                    self.counters["spot_defects"] += 1
            self._stowed(pkg, route.aisle)
        self._go_idle(a)

    def _stowed(self, pkg: _Pkg, location: str) -> None:
        route = self.routes[pkg.route]
        pkg.stowed_at = self.env.now
        pkg.status = "stowed"
        pkg.location = location
        if pkg.ps_state in ("pending_stow", "pending_reinduct", "misdivert", "missed_induct"):
            pkg.ps_state = "resolved"
        if location == route.aisle:
            self.aisle_level[route.aisle] += 1
        self.counters["stowed"] += 1
        self.cluster_stats[route.cluster]["stowed"] += 1
        self._stowed_times.append(self.env.now)

    def _problem_task(self, a: _Assoc):
        if self.pick_started and not len(self.problem_q):
            aisle = self._next_sweep_aisle()
            if aisle is not None:
                yield from self._sweep(a, aisle)
                return
            if self.departures_done:
                self._go_idle(a)
                yield self.env.timeout(_IDLE_POLL_S)
                return
        item = yield from self._wait_get(self.problem_q, a)
        if item is None:
            return
        kind, idx = item
        if kind == "network":
            rec = self.network_missorts[idx]
            self._set_task(a, "problem:network_missort", rec["id"], "Problem solve")
            dur = 90 / a.skill
            yield self.env.timeout(dur)
            a.busy_s += dur
            rec["status"], rec["replanned_at"] = "pending_stow", self.env.now
            self.env.process(self._network_stow(rec))
            self._go_idle(a)
            return
        pkg = self.pkgs[idx]
        if pkg.status not in ("problem_solve", "jackpot"):
            return  # already rolled over at pick start — nothing left to solve
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
                self._late_to_route(pkg)
            else:
                self._stowed(pkg, f"OVERFLOW-{route.cluster}")
            self._go_idle(a)
            return
        if reason == "damaged":
            # damaged flow: PS scan → pending approval (manager review) → pending
            # stow (repacked) or returned to FC / disposed
            pkg.status, pkg.ps_state = "pending_approval", "pending_approval"
            self.counters["damaged_pending_approval"] += 1
            wi = self.work_items.add(
                category="Sort",
                kind="damaged_approval",
                title=f"Approve damaged package {pkg.tracking_id}",
                process="Problem solve",
                priority=2,
                owner="manager",
                started_by="system",
                ref=pkg.tracking_id,
            )
            self.env.process(self._approval(pkg, wi))
            self._go_idle(a)
            return
        pkg.reworked = True
        pkg.problem = None
        if reason in ("misdivert", "missed_induct"):
            pkg.ps_state = "pending_reinduct"
            self.counters["pending_reinduct"] += 1
            pkg.missort = False
        if self.pick_started and not self._forcing():
            pkg.status = "rolled_over"
        else:
            pkg.status = "pending_induct"
            self.induct_q.put(idx, hi=True)
        self._go_idle(a)

    def _approval(self, pkg: _Pkg, wi: dict):
        lo, hi = self.config.quality.damage_approval_minutes
        wait = (lo + (hi - lo) * _u("appr", pkg.tracking_id)) * 60
        waited = 0.0
        while waited < wait and not self.approve_fast:
            yield self.env.timeout(min(60.0, wait - waited))
            waited += 60
        pkg.approval_at = self.env.now
        self.work_items.resolve_item(wi, "approved")
        if pkg.damaged_unrecoverable:
            pkg.status, pkg.ps_state = "held_damaged", "fc_return"
            self.counters["fc_return"] += 1
            return
        pkg.ps_state, pkg.reworked, pkg.problem = "pending_stow", True, None
        if self.pick_started and not self._forcing():
            pkg.status = "rolled_over"
        else:
            pkg.status = "pending_induct"
            self.induct_q.put(pkg.idx, hi=True)

    def _network_stow(self, rec: dict):
        yield self.env.timeout((10 + 25 * _u("nms", rec["id"])) * 60)
        rec["status"], rec["resolved_at"] = "resolved", self.env.now

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
                # stowed into a neighbouring aisle by mistake: invisible to the
                # picker, found by the sweep or the scrub (if at all)
                pkg.status, pkg.left_reason = "left_behind", "missort"
                k = self.aisles.index(route.aisle)
                pkg.location = self.aisles[(k + 1 + pkg.idx % 3) % len(self.aisles)]
                continue
            pkg.status, pkg.picked_at = "picked", self.env.now
            route.picked_count += 1
            self.counters["picked"] += 1
        self.aisle_level[route.aisle] -= sum(
            1 for i in pick_ids if self.pkgs[i].location == route.aisle
        )
        o = self.config.outbound
        if route.forget_bag and route.picked_count > o.packages_per_bag:
            bag = [i for i in pick_ids if self.pkgs[i].status == "picked" and not self.pkgs[i].hv][
                -o.packages_per_bag :
            ]
            for i in bag:
                p = self.pkgs[i]
                p.status, p.left_reason, p.location = "left_behind", "bag_not_loaded", route.aisle
                p.picked_at = None
            route.picked_count -= len(bag)
            route.forgotten = len(bag)
        route.picked_at = self.env.now
        route.status = "staging"
        self.sweep_due[route.aisle] = self.env.now
        route.bags = max(1, math.ceil(max(1, route.picked_count) / o.packages_per_bag))
        route.carts = max(1, math.ceil(route.bags / o.bags_per_cart))
        hv = [i for i in route.packages if self.pkgs[i].hv and self.pkgs[i].status == "hv_in_cage"]
        route.hv_pending = len(hv)
        if hv:
            self.hv_q.put(("handoff", route.idx), hi=True)
        self._set_task(a, "staging", route.route_id, route.staging_location)
        for k in range(route.carts):
            per = lab.stage_minutes_per_cart * 60 / a.skill + self._stage_conflict_s(route)
            yield self.env.timeout(per)
            a.busy_s += per
            if route.misstage and k == route.carts - 1 and route.misstaged_since is None:
                self._misstaged(route, a)
                continue
            route.carts_staged += 1
        if route.forgotten:
            self.notify(
                "supervisor",
                "bag_not_loaded",
                "warning",
                f"{route.route_id}: bag picked but not scanned to cart",
                f"{a.login} staged {route.route_id} one bag short — {route.forgotten} package(s) "
                f"likely left in aisle {route.aisle}. Send the sweeper before the van leaves "
                f"(depart {clock(route.planned_depart / 60)}).",
                route_id=route.route_id,
                aisle=route.aisle,
            )
        for i in route.packages:
            if self.pkgs[i].status == "picked":
                self.pkgs[i].status, self.pkgs[i].staged_at = "staged", self.env.now
        self._maybe_staged(route)
        self._go_idle(a)

    def _stage_conflict_s(self, route: _Route) -> float:
        """A foreign cart sitting in this route's staging location slows the
        stager down (they have to move it aside and re-check labels)."""
        for r in self.routes:
            if r.misstaged_at == route.staging_location and r.misstage_fixed_at is None:
                return 90.0
        return 0.0

    def _misstaged(self, route: _Route, a: _Assoc) -> None:
        n = len(self.routes)
        other = self.routes[(route.idx + 2) % n]
        route.misstaged_at = other.staging_location
        route.misstaged_by = a.login
        route.misstaged_since = self.env.now
        self.counters["misstaged"] += 1
        self.log(
            "floor",
            f"Wrong staging scan: {route.route_id} cart scanned into {other.staging_location} "
            f"(expected {route.staging_location})",
        )
        self.notify(
            "supervisor",
            "wrong_staging_scan",
            "critical",
            f"Wrong staging scan — {route.route_id}",
            f"{a.login} scanned a {route.route_id} cart into {other.staging_location} "
            f"(belongs at {route.staging_location}). {route.route_id} can't load until it is "
            f"moved; {other.route_id}'s location is obstructed.",
            route_id=route.route_id,
            location=other.staging_location,
            expected=route.staging_location,
            associate=a.login,
        )
        if route.driver is not None:
            d = self.drivers[route.driver]
            self.notify(
                "dsp",
                "staging_change",
                "info",
                f"{route.route_id}: hold at {route.staging_location}",
                f"{d.driver_id} ({route.dsp}): one cart is being moved to "
                f"{route.staging_location}; do not load from {other.staging_location}.",
                route_id=route.route_id,
                dsp=route.dsp,
            )
        if other.driver is not None:
            self.notify(
                "dsp",
                "staging_change",
                "info",
                f"{other.route_id}: foreign cart at {other.staging_location}",
                f"{self.drivers[other.driver].driver_id} ({other.dsp}): a {route.route_id} cart "
                f"is in your location — check cart labels before loading.",
                route_id=other.route_id,
                dsp=other.dsp,
            )
        route.restage_ev = self.env.event()
        self.env.process(self._misstage_watch(route))

    def _misstage_watch(self, route: _Route):
        yield self.env.timeout(route.misstage_notice_s) | route.restage_ev
        route.restaging = True
        who = "supervisor-directed" if route.restage_ev.triggered else "noticed on the floor"
        yield self.env.timeout(self.config.outbound.restage_minutes * 60)
        route.misstage_fixed_at = self.env.now
        self.work_items.resolve("wrong_staging_scan", route.route_id, "cart restaged")
        wrong = route.misstaged_at
        route.misstaged_at = None
        route.restaging = False
        route.carts_staged += 1
        mins = (self.env.now - route.misstaged_since) / 60
        self.log(
            "floor",
            f"{route.route_id} cart moved from {wrong} to "
            f"{route.staging_location} ({who}, {mins:.0f} min)",
        )
        self.notify(
            "supervisor",
            "restaged",
            "info",
            f"{route.route_id} cart restaged",
            f"Cart moved {wrong} → {route.staging_location} after {mins:.0f} min ({who}).",
            route_id=route.route_id,
        )
        self._maybe_staged(route)

    # --- sweep (problem solve) -------------------------------------------------

    def _aisle_picked(self, aisle: str) -> bool:
        return all(r.picked_at is not None or r.sidelined for r in self.routes if r.aisle == aisle)

    def _due_aisles(self) -> list[str]:
        """Aisles where a route finished picking since the last sweep pass,
        oldest first — the sweeper follows the pickers."""
        due = [
            x
            for x, t in self.sweep_due.items()
            if t > self.swept.get(x, -1.0) and x not in self.sweeping
        ]
        return sorted(due, key=lambda x: self.sweep_due[x])

    def _sweep_open(self) -> bool:
        return bool(self.sweep_priority or self._due_aisles())

    def _next_sweep_aisle(self) -> str | None:
        while self.sweep_priority:
            x = self.sweep_priority.pop(0)
            if x not in self.sweeping:
                return x
        due = self._due_aisles()
        return due[0] if due else None

    def _sweep(self, a: _Assoc, aisle: str):
        self.sweeping.add(aisle)
        self.sweep_passes[aisle] += 1
        self._set_task(a, "sweeping", aisle, f"Aisle {aisle}")
        dur = self.config.labor.sweep_minutes_per_aisle * 60 / a.skill
        yield self.env.timeout(dur)
        a.busy_s += dur
        miss = self.config.labor.sweep_miss_rate
        found = [
            p
            for p in self.pkgs
            if p.status == "left_behind"
            and p.location == aisle
            and random.Random(
                f"sweep:{self.config.seed}:{p.idx}:{self.sweep_passes[aisle]}"
            ).random()
            >= miss
        ]
        by_route: dict[int, list[_Pkg]] = defaultdict(list)
        for p in found:
            by_route[p.route].append(p)
        for ridx, pkgs in by_route.items():
            route = self.routes[ridx]
            if route.departed_at is None:
                walk = 60 / a.skill
                self._set_task(a, "sweep_restage", route.route_id, route.staging_location)
                yield self.env.timeout(walk)
                a.busy_s += walk
            if route.departed_at is None:
                for p in pkgs:
                    p.status = "staged" if route.staged_at is not None else "picked"
                    p.staged_at = self.env.now if route.staged_at is not None else None
                    p.picked_at = self.env.now
                    p.recovered, p.location = "sweep_staged", route.staging_location
                route.picked_count += len(pkgs)
                self.counters["sweep_staged"] += len(pkgs)
                self.work_items.resolve("bag_not_loaded", route.route_id, "found by sweep")
                outcome = f"staged to {route.route_id}'s cart at {route.staging_location}"
            else:
                for p in pkgs:
                    p.status, p.recovered, p.location = "cluster_transfer", "cluster_transfer", "CT"
                self.counters["cluster_transfer"] += len(pkgs)
                self.work_items.resolve("bag_not_loaded", route.route_id, "cluster transfer")
                outcome = f"{route.route_id} already departed → cluster transfer to next cycle"
            self.sweep_log.append(
                {
                    "minute": self.env.now / 60,
                    "clock": clock(self.env.now / 60),
                    "aisle": aisle,
                    "route_id": route.route_id,
                    "packages": len(pkgs),
                    "reasons": sorted({p.left_reason or "?" for p in pkgs}),
                    "outcome": "staged" if route.departed_at is None else "cluster_transfer",
                    "by": a.login,
                }
            )
            self.notify(
                "supervisor",
                "sweep_found",
                "info" if route.departed_at is None else "warning",
                f"Sweep found {len(pkgs)} package(s) in {aisle}",
                f"{a.login}: {len(pkgs)} {route.route_id} package(s) — {outcome}.",
                route_id=route.route_id,
                aisle=aisle,
            )
        self.swept[aisle] = self.env.now
        self.sweeping.discard(aisle)
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
                    rec = self.apply(
                        Intervention(kind="reassign_standby", target=r.route_id, source="dsp_auto")
                    )
                    if rec["effect"].startswith("no-op"):
                        self._no_driver(r)
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
        yield from self._vsa(d)
        if d.state == "released":
            return
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

    def _vsa(self, d: _Driver):
        """Yard marshal vehicle safety audit before loading. Marshals are a
        finite resource (queue at wave peaks); a defect is fixed on site or
        grounds the van until a replacement arrives."""
        disp = self.config.dispatch
        route = self.routes[d.route]
        d.state = "vsa"
        k = min(range(len(self._marshal_free)), key=self._marshal_free.__getitem__)
        start = max(self.env.now, self._marshal_free[k])
        dur = disp.vsa_minutes * 60
        self._marshal_free[k] = start + dur
        d.vsa_wait_s = start - self.env.now
        yield self.env.timeout(start + dur - self.env.now)
        d.vsa_at = self.env.now
        if d.vsa_u < disp.vsa_ground_rate:
            d.vsa_result, d.state, d.grounded_at = "grounded", "grounded", self.env.now
            self.counters["vsa_grounded"] += 1
            self.log(
                "dispatch",
                f"VSA FAIL: {d.driver_id}'s van grounded ({d.vsa_defect}) — {route.route_id}",
            )
            self.notify(
                "supervisor",
                "van_grounded",
                "critical",
                f"Van grounded — {route.route_id}",
                f"Yard marshal failed {d.driver_id}'s van ({d.dsp}): {d.vsa_defect}. "
                f"{route.route_id} (depart {clock(route.planned_depart / 60)}) needs a "
                "replacement van.",
                route_id=route.route_id,
                dsp=d.dsp,
            )
            self.notify(
                "dsp",
                "van_grounded",
                "critical",
                f"{d.dsp}: van grounded on {route.route_id}",
                f"{d.driver_id}'s van failed VSA ({d.vsa_defect}) and is grounded. Follow-up: "
                "replacement van, defect report, van removed from service until repaired.",
                route_id=route.route_id,
                dsp=d.dsp,
            )
            d.van_event = self.env.event()
            self.env.process(self._dsp_default_replace(d))
            yield d.van_event
            if d.state == "released":
                return
            d.state = "vsa"
            yield self.env.timeout(dur)  # replacement van audited
            d.vsa_result = "replaced"
            self.work_items.resolve("van_grounded", self.routes[d.route].route_id, "van replaced")
        elif d.vsa_u < disp.vsa_ground_rate + disp.vsa_minor_rate:
            d.vsa_result, d.state = "minor_fixed", "vsa_fix"
            self.counters["vsa_minor"] += 1
            self.log(
                "dispatch", f"VSA: {d.driver_id} minor defect ({d.vsa_defect}), fixing on site"
            )
            yield self.env.timeout(d.vsa_fix_s)
        else:
            d.vsa_result = "pass"
        self.counters["vsa_done"] += 1
        d.state = "checked_in"

    def _dsp_default_replace(self, d: _Driver):
        yield self.env.timeout(self.config.dispatch.dsp_replace_after_minutes * 60)
        if d.van_request is None and d.state == "grounded":
            self._request_van(d, "dsp_default")

    def _request_van(self, d: _Driver, source: str) -> str:
        disp = self.config.dispatch
        route = self.routes[d.route]
        if self.spare_vans.get(d.dsp, 0) > 0:
            self.spare_vans[d.dsp] -= 1
            kind, lead = f"{d.dsp} spare van", disp.replacement_van_minutes
        else:
            donor = next((k for k, v in self.spare_vans.items() if v > 0), None)
            if donor:
                self.spare_vans[donor] -= 1
                kind, lead = f"van borrowed from {donor}", disp.borrowed_van_minutes
            else:
                kind, lead = "rental van", disp.rental_van_minutes
        d.van_request = kind
        d.van_eta = self.env.now + lead * 60
        self.notify(
            "dsp",
            "replacement_van",
            "warning",
            f"{route.route_id}: {kind} dispatched",
            f"{kind} for {d.driver_id}, ETA {clock(d.van_eta / 60)} (requested by {source}).",
            route_id=route.route_id,
            dsp=d.dsp,
        )
        self.env.process(self._van_arrives(d, lead * 60))
        return f"{kind} requested for {route.route_id}, ETA {clock(d.van_eta / 60)}"

    def _van_arrives(self, d: _Driver, lead: float):
        yield self.env.timeout(lead)
        self.log("dispatch", f"Replacement van arrived for {self.routes[d.route].route_id}")
        if d.van_event is not None and not d.van_event.triggered:
            d.van_event.succeed()

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
            self.departures_done_at = now
            self.log("shift", "All routes departed — associates finishing their shift")
            # inducted into today's cycle after the cut without a cycle change →
            # held as wrong-cycle induct (needs problem solve tomorrow)
            held = 0
            for p in self.pkgs:
                if (
                    p.status == "rolled_over"
                    and p.inducted_at is not None
                    and p.inducted_at >= self.cutoff
                ):
                    p.status = "held_wrong_cycle"
                    held += 1
            self.counters["held_wrong_cycle"] += held
            self.env.process(self.closeout.run())
            self.env.process(self._end_of_day())

    def _end_of_day(self):
        last = max((d.return_at or 0) for d in self.drivers)
        yield self.env.timeout(max(0.0, min(last, DAY_END_MINUTE * 60) - self.env.now))
        if not self.closeout.complete:
            yield self.closeout.done_event
        self.day_complete = True

    # --- cycle --------------------------------------------------------------

    def _cycle_process(self):
        while self.env.now < self.cutoff:
            yield self.env.timeout(self.cutoff - self.env.now)
        self.pick_started = True
        self.log("cycle", f"Pick started for {self.config.cycle.name} — induct blocked")
        forcing = self._forcing()
        if not forcing:
            for pkg in self.pkgs:
                if pkg.status in ("pending_induct", "problem_solve", "jackpot", "missed_induct"):
                    pkg.status = "rolled_over"
        on_floor = sum(
            1 for p in self.pkgs if p.status == "rolled_over" and p.arrived_at is not None
        )
        self.notify(
            "manager",
            "cycle_pick_started",
            "warning",
            f"Pick has started for {self.config.cycle.name} — induct is blocked",
            f"{on_floor} package(s) on the floor missed the cycle. Change the cycle (move them to "
            "tomorrow cleanly), force-induct late volume whose routes haven't left, or enable "
            "the next cycle for new arrivals.",
        )
        for r in self.routes:
            if r.status == "not_ready":
                r.status = "ready"
        for a in self.assocs:
            if a.role == "induct" and not forcing:
                self.reassign(a, "pick")
        # stowers keep draining the stow buffer (see _stow_draining), then pick

    def _drain_end(self):
        """When the stow drain after pick start ends, whatever is still in the
        stow buffer missed the cycle (rolls over)."""
        while True:
            end = self.cutoff + self.config.stow.drain_minutes * 60
            if self.env.now >= end:
                break
            yield self.env.timeout(end - self.env.now)
        n = 0
        for p in self.pkgs:
            if p.status in ("stow_buffered", "pending_stow"):
                if p.status == "stow_buffered":
                    self.n_buffered -= 1
                    if p.finger:
                        self.finger_stats[p.finger]["buffer"] -= 1
                p.status = "rolled_over"
                n += 1
        if n:
            self.log("cycle", f"Stow drain closed — {n} buffered package(s) rolled over")

    def _sampler(self):
        bucket = SERIES_BUCKET_MINUTES * 60
        last: Counter = Counter()
        while not self.day_complete:
            t = self.env.now
            if t % bucket == 0:
                s = self.series
                s["minute"].append(t / 60)
                for k in (
                    "arrived",
                    "inducted",
                    "stowed",
                    "picked",
                    "inducted_auto",
                    "inducted_manual",
                ):
                    s[k].append(self.counters[k] - last[k])
                    last[k] = self.counters[k]
                s["labor_yard_marshal"].append(
                    len(self._marshal_free) * SERIES_BUCKET_MINUTES / 60
                    if self.env.now >= (self.cutoff - 60 * 60)
                    else 0
                )
                s["labor_idle"].append(
                    sum(1 for a in self.assocs if a.present and a.task == "idle")
                    * SERIES_BUCKET_MINUTES
                    / 60
                )
                s["stowers_active"].append(self.active("stow"))
                s["wip_minutes"].append(round(self.wip_minutes(), 1))
                s["departed_routes"].append(
                    sum(1 for r in self.routes if r.departed_at is not None)
                )
                for role in ("induct", "stow", "pick", "problem_solve", "high_value"):
                    s[f"labor_{role}"].append(self.active(role) * SERIES_BUCKET_MINUTES / 60)
            st = self.config.settings
            interval = st.compliance_interval_minutes * 60
            start = self.config.induct.start_minute * 60
            w = st.induct_fph_window_minutes * 60
            # skip breaks and the FPH window after one (rolling FPH reads 0 there)
            settling = self.in_break(t) or self.in_break(t - w)
            if start <= t < self.cutoff and not settling:
                self._wip_samples.append(self.wip_minutes())
            if t > start and t <= self.cutoff + 1 and (t - start) % interval == 0:
                # documented: compliance over 15-minute intervals within thresholds
                samples = [x for x in self._wip_samples if x is not None]
                self._wip_samples = []
                if samples:
                    avg = sum(min(x, 999.0) for x in samples) / len(samples)
                    ok = st.stow_wip_lower_min <= avg <= st.stow_wip_upper_min
                    self.wip_intervals.append(
                        {"end": t / 60, "clock": clock(t / 60), "wip": round(avg, 1), "ok": ok}
                    )
            self.work_items.tick()
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
        if old.state in ("checked_in", "loading", "vsa", "vsa_fix", "grounded"):
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
        self._draw_vsa(new, rng)
        self.drivers.append(new)
        r.driver = new.idx
        self.env.process(self._standby_proc(new))
        eta = clock((now + lead) / 60)
        return f"{r.dsp} standby {new.driver_id} assigned to {r.route_id}, ETA {eta}"

    def _no_driver(self, r: _Route) -> None:
        """No driver and no standby anywhere: the route can't go out today.
        Its packages stay in the station (not attempted) and roll to tomorrow."""
        r.sidelined = True
        n = 0
        for i in r.packages:
            p = self.pkgs[i]
            if p.status in ("staged", "picked", "stowed", "hv_in_cage"):
                p.status, p.attempted = "rolled_over", None
                n += 1
        self.notify(
            "manager",
            "route_unassigned",
            "critical",
            f"{r.route_id}: no driver available",
            f"{r.dsp} had no standby left; {n} package(s) on {r.route_id} roll to tomorrow.",
            route_id=r.route_id,
        )
        if (
            all(x.departed_at is not None or x.sidelined for x in self.routes)
            and not self.departures_done
        ):
            self.departures_done = True
            self.departures_done_at = self.env.now
            self.env.process(self.closeout.run())
            self.env.process(self._end_of_day())

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

    def _act_restage_cart(self, iv, n):
        r = self.route_by_id(iv.target)
        if r is None or r.misstaged_at is None or r.misstage_fixed_at is not None:
            return "no-op: no misstaged cart for that route"
        if r.restaging or r.restage_ev.triggered:
            return f"no-op: {r.route_id} cart already being moved"
        r.restage_ev.succeed()
        return (
            f"{r.route_id}: nearest associate sent to move the cart {r.misstaged_at} → "
            f"{r.staging_location} (~{self.config.outbound.restage_minutes:.0f} min); "
            "DSPs of both routes told to check labels"
        )

    def _act_direct_sweep(self, iv, n):
        aisle = iv.target
        if aisle not in self.aisles:
            return "no-op: unknown aisle"
        if aisle in self.sweep_priority or aisle in self.sweeping:
            return f"no-op: aisle {aisle} already being swept"
        if not any(a.present and a.role == "problem_solve" for a in self.assocs):
            if not self._take_associates(1, "problem_solve", "pick"):
                return "no-op: no sweeper available"
        self.sweep_priority.append(aisle)
        return f"sweeper directed to aisle {aisle} next"

    def _act_request_replacement_van(self, iv, n):
        r = self.route_by_id(iv.target)
        if r is None or r.driver is None:
            return "no-op: unknown route"
        d = self.drivers[r.driver]
        if d.state != "grounded":
            return "no-op: van not grounded"
        if d.van_request:
            return f"no-op: {d.van_request} already on the way"
        return self._request_van(d, iv.source)

    def _act_add_yard_marshal(self, iv, n):
        if self.extra_marshals >= 2:
            return "no-op: 2 extra yard marshals already assigned"
        got = self._take_associates(1, "yard_marshal", "pick") or self._take_associates(
            1, "yard_marshal", "problem_solve"
        )
        if not got:
            return "no-op: no associate free to marshal the yard"
        self.extra_marshals += 1
        self._marshal_free.append(self.env.now)
        return f"extra yard marshal assigned to VSA checks ({len(self._marshal_free)} marshals)"

    def _act_check_ferry(self, iv, n):
        return self.closeout.request_ferry_check(iv.source)

    def _act_draft_gtdr(self, iv, n):
        return self.closeout.draft_gtdrs(iv.source)

    def _act_replan_next_day(self, iv, n):
        return self.closeout.request_replan(iv.source)

    def _act_offer_vet(self, iv, n):
        return self.closeout.opportunities.post("VET", max(1, n), iv.params.get("frame"), iv.source)

    def _act_offer_vto(self, iv, n):
        return self.closeout.opportunities.post("VTO", max(1, n), iv.params.get("frame"), iv.source)

    # --- v2 levers: cycles, fingers, approvals, trips, planning --------------------

    def _act_force_induct(self, iv, n):
        """Keep induct open after pick start for late volume whose routes
        haven't departed (bounded window)."""
        cap = self.config.cycle.max_force_induct_minutes
        minutes = max(5.0, min(float(iv.amount or 15), cap))
        if self.env.now < self.cutoff - 60 * 60:
            return "no-op: force induct is for the pick-start window (within 60 min of pick start)"
        start = max(self.env.now, self.cutoff)
        end = start + minutes * 60
        if self.force_until is not None and self.force_until >= end:
            return "no-op: force induct already open that long"
        self.force_until = end
        requeued = 0
        if self.pick_started:
            for p in self.pkgs:
                if p.status == "rolled_over" and p.arrived_at is not None and p.inducted_at is None:
                    p.status = "pending_induct"
                    self.induct_q.put(p.idx, hi=True)
                    requeued += 1
            for a in self.assocs:
                if a.present and a.home_role == "induct" and a.home_line and a.role == "pick":
                    if a.task not in ("picking", "staging"):
                        self.reassign(a, "induct")
                        a.line = a.home_line
        self.cycle_changes.append(
            {
                "clock": clock(self.env.now / 60),
                "action": "force_induct",
                "minutes": minutes,
                "packages": requeued,
            }
        )
        return (
            f"force induct open until {clock(end / 60)} ({minutes:.0f} min): late volume goes "
            f"straight to its route if the van hasn't left; {requeued} package(s) re-queued"
        )

    def _act_change_cycle(self, iv, n):
        """Move rolled-over volume on the floor into tomorrow's cycle cleanly
        (no wrong-cycle holds, no re-induct tomorrow)."""
        if not self.pick_started:
            return "no-op: change cycle applies once pick has started"
        moved = 0
        for p in self.pkgs:
            if p.status == "rolled_over" and p.arrived_at is not None:
                p.status = "next_cycle"
                moved += 1
        self.counters["next_cycle"] += moved
        self.cycle_changes.append(
            {"clock": clock(self.env.now / 60), "action": "change_cycle", "packages": moved}
        )
        self.work_items.resolve("cycle_pick_started", None, "cycle changed")
        return f"{moved} package(s) moved to tomorrow's cycle (no wrong-cycle holds)"

    def _act_enable_cycle(self, iv, n):
        """Enable the next cycle on this node for N hours: late arrivals after
        pick start are received straight into tomorrow's cycle."""
        hours = max(1.0, min(float(iv.amount or 4), 8))
        self.next_cycle_until = max(self.env.now, self.cutoff) + hours * 3600
        self.cycle_changes.append(
            {"clock": clock(self.env.now / 60), "action": "enable_cycle", "hours": hours}
        )
        return f"next cycle enabled until {clock(self.next_cycle_until / 60)} for late arrivals"

    def _act_rebalance_finger(self, iv, n):
        """Point a full finger's cluster at the other finger (container builders follow)."""
        cluster = (iv.target or "").replace("FINGER-", "") or None
        fingers = {
            f"FINGER-{c}": self.finger_stats[f"FINGER-{c}"]["buffer"]
            for c in self.config.sort.clusters
        }
        if cluster is None:
            cluster = max(fingers, key=fingers.get).replace("FINGER-", "")
        others = [f for f in fingers if f != f"FINGER-{cluster}"]
        if not others:
            return "no-op: only one finger"
        to = min(others, key=fingers.get)
        if self.finger_rebalanced.get(cluster) == to:
            return f"no-op: cluster {cluster} already rebalanced to {to}"
        self.finger_rebalanced[cluster] = to
        return f"cluster {cluster} volume rebalanced from FINGER-{cluster} to {to}"

    def _act_approve_damaged(self, iv, n):
        pending = sum(1 for p in self.pkgs if p.ps_state == "pending_approval")
        self.approve_fast = True
        return f"manager review expedited: {pending} damaged package(s) pending approval cleared"

    def _act_watch_trip(self, iv, n):
        tid = iv.target
        if not any(t.trip_id == tid for t in self.config.linehauls):
            return "no-op: unknown trip"
        if tid in self.watch:
            self.watch.discard(tid)
            return f"{tid} removed from the watch list"
        self.watch.add(tid)
        return f"{tid} added to the watch list"

    def _act_post_opportunity(self, iv, n):
        return self.closeout.opportunities.post(
            iv.target or "VET", int(iv.amount or 1), iv.params.get("frame"), iv.source
        )

    def _act_close_window(self, iv, n):
        return self.closeout.opportunities.close(iv.target, iv.source)

    def _act_rerun_rotation(self, iv, n):
        return self.closeout.rerun_rotation(iv.source)

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

    def inc_pending_stow(self) -> int:
        """INC (documented): valid induct scan, not stowed."""
        return (
            self.n_buffered + len(self.stow_q) + sum(1 for a in self.assocs if a.task == "stowing")
        )

    def stow_fph(self) -> float:
        """Stowed per hour, rolling window (window = settings' FPH window)."""
        w = self.config.settings.induct_fph_window_minutes
        return self.rate_window(self._stowed_times, w) * 60 / w

    def induct_fph(self) -> float:
        """Documented: inducted volume in the past rolling 10 min, per hour."""
        w = self.config.settings.induct_fph_window_minutes
        return self.rate_window(self._inducted_times, w) * 60 / w

    def wip_minutes(self) -> float | None:
        """Stow WIP (documented): (inducted pending stow ÷ Stow FPH) × 60.
        None when nothing is pending; 999 caps "no stow flow yet"."""
        inc = self.inc_pending_stow()
        if inc == 0:
            return 0.0
        fph = self.stow_fph()
        if fph <= 0:
            return 999.0
        return inc / fph * 60

    def rate_window(self, times: list[float], minutes: float) -> int:
        lo = self.env.now - minutes * 60
        n = 0
        for t in reversed(times):
            if t < lo:
                break
            n += 1
        return n

    def rate_last_hour(self, times: list[float]) -> int:
        lo = self.env.now - 3600
        n = 0
        for t in reversed(times):
            if t < lo:
                break
            n += 1
        return n
