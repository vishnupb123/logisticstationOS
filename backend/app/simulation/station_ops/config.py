"""Typed configuration for the Station Operations Twin (v2, ADR-0011/0012).

Every count, rate and clock time is configuration (docs/DIGITAL_TWIN_SPEC.md
"Configuration, not hardcoding"); defaults describe a fictional, mid-sized
synthetic station and are assumptions, not facts about any real site.

Times are minutes after local midnight of the out-for-delivery (OFD) date.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class FerryRevision(BaseModel):
    """An ETA update the station *learns* at `reveal_minute` (the truckfile's
    ferry checks through the night). The twin always uses the trip's true
    `delay_minutes`; agents only ever see the latest revealed revision."""

    reveal_minute: float
    delay_minutes: float


class LinehaulPlan(BaseModel):
    trip_id: str
    origin: str
    planned_arrival_minute: float
    #: True delay (what actually happens).
    delay_minutes: float = 0
    #: What the station knows, and when. Empty = the delay is known from the start.
    revisions: list[FerryRevision] = []
    cancelled: bool = False
    volume: int
    via_ferry: bool = False
    ferry_sailing: str | None = None
    delay_reason: str | None = None
    #: Facility sequence: [{"from", "to", "mode": road|ferry, "planned_depart",
    #: "planned_arrive"}] — the trip's multi-stop path (synthetic codes).
    legs: list[dict] = []
    operator_type: Literal["single", "team"] = "single"
    tractor: str | None = None
    trailer: str | None = None
    #: Share of the trip's volume outside the upstream container plan.
    unplanned_share: float = Field(0.2, ge=0, le=1)

    def known_delay(self, minute: float) -> float:
        if not self.revisions:
            return self.delay_minutes
        known = [r for r in self.revisions if r.reveal_minute <= minute]
        return known[-1].delay_minutes if known else 0.0


class InductOutage(BaseModel):
    """Planned/known outage (e.g. maintenance) — visible to agents in advance."""

    line: int
    start_minute: float
    duration_minutes: float


DisruptionKind = Literal[
    "line_jam",  # unplanned induct line stop (target: line number)
    "scanner_degradation",  # no-read rate spike on a line (magnitude = multiplier)
    "absenteeism",  # associates leave / call out (magnitude = headcount)
    "traffic_incident",  # driver travel delay in a map sector (magnitude = minutes)
    "weather",  # delivery-failure multiplier for the rest of the day
    "volume_surge",  # unplanned (unmanifested) volume arrives (magnitude = packages)
]


class Disruption(BaseModel):
    """Something that happens without warning — revealed only when it occurs."""

    kind: DisruptionKind
    at_minute: float
    duration_minutes: float = 0
    target: str | None = None
    magnitude: float = 1.0
    source: Literal["scenario", "random", "injected"] = "scenario"


class InductConfig(BaseModel):
    lines: int = 2
    #: Manual induct line rate (proposed).
    rate_pph_per_line: float = 1000
    #: Lines 1..automated_lines are automated (auto-scan induct loader + labeler +
    #: pushers/diverters feeding auto-divert fingers); the rest are manual.
    automated_lines: int = 1
    automated_rate_pph: float = 1250
    #: Share of packages the automated line can take; non-conveyables go to a
    #: manual line (non-con manual handling). Proposed.
    conveyable_share: float = Field(0.88, ge=0, le=1)
    start_minute: float = 150  # 02:30 — main sort crew (site profile)
    no_read_rate: float = Field(0.012, ge=0, le=1)
    multi_read_rate: float = Field(0.004, ge=0, le=1)
    #: Sort label misapplied → misdivert / relabel at problem solve.
    misapplied_label_rate: float = Field(0.003, ge=0, le=1)
    #: Package carried past the induct scan without a scan (found later by dwell).
    missed_induct_rate: float = Field(0.002, ge=0, le=1)
    outages: list[InductOutage] = []


class SortConfig(BaseModel):
    missort_rate: float = Field(0.008, ge=0, le=1)
    #: Share of misdiverts caught at stow (stow scan to problem solve → re-induct);
    #: the rest are left behind in the wrong aisle.
    missort_catch_rate: float = Field(0.7, ge=0, le=1)
    aisles_per_cluster: int = 20
    clusters: list[str] = ["A", "B"]
    #: Bay capacity headroom over the aisle's expected volume; overflow → jackpot.
    bay_headroom: float = 1.15
    #: Container fill + transport from induct to the aisle (stow buffer), minutes
    #: (uniform range per package). This is why a healthy stow WIP is 15–30 min.
    stow_buffer_minutes: tuple[float, float] = (10.0, 24.0)
    #: Auto-divert finger: packages in a finger's buffer before its bays are full
    #: and further volume diverts to the jackpot ("full bay").
    finger_bay_capacity: int = 650
    #: Packages sidelined at induct for another station / carrier (network missort).
    network_missort_rate: float = Field(0.003, ge=0, le=1)


class StowConfig(BaseModel):
    stowers: int = 10
    rate_pph_per_stower: float = 220
    #: Stower places a package on the wrong rack (stower FSAF), found by sweep.
    stower_error_rate: float = Field(0.002, ge=0, le=1)
    #: Share of stows audited by a spot check.
    spot_check_rate: float = Field(0.03, ge=0, le=1)
    #: After pick start stowers keep draining the stow buffer this long.
    drain_minutes: float = 30


class QualityConfig(BaseModel):
    high_value_rate: float = Field(0.012, ge=0, le=1)
    unmanifested_rate: float = Field(0.02, ge=0, le=1)
    damaged_rate: float = Field(0.001, ge=0, le=1)
    damaged_unrecoverable_share: float = Field(0.5, ge=0, le=1)
    #: Damaged packages wait for a manager review (pending approval), minutes.
    damage_approval_minutes: tuple[float, float] = (15.0, 45.0)
    hv_scan_in_seconds: float = 45
    hv_handoff_seconds: float = 40


class Break(BaseModel):
    start_minute: float
    minutes: float
    label: str = "break"


class SettingsConfig(BaseModel):
    """The station's Settings page. `documented` = the owner's definitions
    sheet; `proposed` = our assumption (docs/OPEN_QUESTIONS.md)."""

    #: documented default 15 / 30 min ("unless adjusted in Settings").
    stow_wip_lower_min: float = 15
    stow_wip_upper_min: float = 30
    #: proposed (the network goal is not in the definitions).
    stow_wip_compliance_target: float = Field(0.70, ge=0, le=1)
    #: documented: compliance in 15-minute intervals.
    compliance_interval_minutes: int = 15
    #: documented: induct FPH actual = rolling 10 minutes expressed per hour.
    induct_fph_window_minutes: int = 10
    #: documented: a gap between consecutive packages on one belt in (20 s, 120 s) is a defect.
    belt_gap_defect_seconds: tuple[float, float] = (20.0, 120.0)
    #: documented: induct dwell = neither inducted nor stowed for more than 60 min.
    induct_dwell_minutes: float = 60
    #: documented: pending re-induct window — from 60 min before induct end to 30 after.
    reinduct_window_before_minutes: float = 60
    reinduct_window_after_minutes: float = 30
    #: proposed: fast start allowance and break schedule (belt stops).
    fast_start_minutes: float = 10
    breaks: list[Break] = [
        Break(start_minute=300, minutes=15, label="break"),
        Break(start_minute=420, minutes=30, label="lunch"),
    ]
    #: proposed: indirect-time allowance behind "TPH with/without indirect".
    indirect_allowance: float = Field(0.08, ge=0, le=0.5)


class LaborConfig(BaseModel):
    problem_solvers: int = 2
    high_value_associates: int = 2
    dedicated_pickers: int = 4
    attendance_rate: float = Field(0.96, ge=0, le=1)
    #: Associates that can be called in on voluntary extra time (VET).
    flex_pool: int = 8
    vet_lead_minutes: float = 45
    skill_sigma: float = 0.15
    pick_seconds_per_package: float = 2.5
    pick_base_minutes: float = 4
    stage_minutes_per_cart: float = 2.5
    #: Problem-solve sweep: walk every aisle once its routes are picked.
    sweep_minutes_per_aisle: float = 1.5
    #: Chance a sweeper walks past a left-behind item (found later by the scrub).
    sweep_miss_rate: float = Field(0.1, ge=0, le=1)


class CycleConfig(BaseModel):
    name: str = "CYCLE_1"
    #: Once pick starts, induct into the cycle is blocked; un-inducted volume rolls
    #: over unless the cycle is changed / force-inducted.
    pick_start_minute: float = 600  # 10:00 (site profile)
    #: Separate cycles shown on dwell / receive / induct (high value runs as its own).
    high_value_cycle: str = "High_Value"
    #: Unplanned volume is assigned to the cycle at induct (dynamic plan).
    dynamic_plan: bool = True
    #: Maximum force-induct window after pick start, minutes.
    max_force_induct_minutes: float = 30
    #: Delivery windows (for "by scheduled delivery window" views), minutes.
    delivery_windows: list[tuple[float, float]] = [(600, 900), (900, 1140), (1140, 1320)]


class DspConfig(BaseModel):
    code: str
    #: Probability a driver of this DSP leaves late on a given day.
    late_rate: float
    standby_drivers: int = 1
    #: Spare vans the DSP can send when a van is grounded at the VSA.
    spare_vans: int = 1


class DispatchConfig(BaseModel):
    dsps: list[DspConfig] = [
        DspConfig(code="DSP-ALPHA", late_rate=0.03, standby_drivers=2),
        DspConfig(code="DSP-BRAVO", late_rate=0.06, standby_drivers=1),
        DspConfig(code="DSP-CHARLIE", late_rate=0.04, standby_drivers=1),
        DspConfig(code="DSP-DELTA", late_rate=0.08, standby_drivers=1),
    ]
    #: Mean lateness (minutes) when a driver is late; lognormal spread.
    late_mean_minutes: float = 14
    #: Share of a late driver's lateness that a notification removes
    #: (they didn't know their wave/time — vs. traffic they can't avoid).
    notify_recoverable_share: float = 0.6
    check_in_lead_minutes: float = 30
    #: Loading after the VSA (VSA + load ≈ the 10-min launch-pad window).
    load_minutes: float = 8
    standby_lead_minutes: float = 30
    drive_speed_kmh: float = 35
    #: OTD tolerance — a proposed assumption, not a known org standard.
    otd_tolerance_minutes: float = 0
    swipe_forget_rate: float = Field(0.15, ge=0, le=1)
    delivery_failure_rate: float = Field(0.015, ge=0, le=1)
    customer_return_rate: float = Field(0.02, ge=0, le=1)
    #: Yard marshals doing vehicle safety audits (VSA) at check-in.
    yard_marshals: int = 4
    vsa_minutes: float = 2
    #: Share of vans with a defect fixed on site (wiper, tyre pressure, ...).
    vsa_minor_rate: float = Field(0.05, ge=0, le=1)
    #: Share of vans that fail and are grounded (unsafe to drive).
    vsa_ground_rate: float = Field(0.02, ge=0, le=1)
    #: Spare van lead time from the DSP's own lot / from another DSP / rental.
    replacement_van_minutes: float = 30
    borrowed_van_minutes: float = 40
    rental_van_minutes: float = 120
    #: Default DSP behaviour: request a replacement this long after grounding.
    dsp_replace_after_minutes: float = 20


class OutboundConfig(BaseModel):
    routes: int = 80
    wave_stage_by_minutes: list[float] = [650, 670, 690, 710, 730]  # 10:50..12:10
    #: Planned departure = stage-by + this.
    depart_after_stage_by_minutes: float = 20
    route_duration_min_hours: float = 7.5
    route_duration_max_hours: float = 9.5
    driver_window_hours: float = 10
    packages_per_bag: int = 12
    bags_per_cart: int = 6
    #: Shipments-per-route flags (low/high), as in pick tooling.
    spr_low: int = 60
    spr_high: int = 270
    #: Per-route chance a cart is scanned into the wrong staging location.
    misstage_rate: float = Field(0.05, ge=0, le=1)
    #: Minutes until someone notices a misstaged cart unaided (uniform range).
    misstage_notice_minutes: tuple[float, float] = (10, 30)
    restage_minutes: float = 3
    #: Per-route chance a picker leaves a bag in the aisle (not on the cart).
    bag_forget_rate: float = Field(0.05, ge=0, le=1)


class BacklogConfig(BaseModel):
    """Carry-over packages from previous days (ageing), as a share of volume."""

    rollover_share: float = 0.015
    retained: int = 90
    marked_missing: int = 40
    on_road_unconfirmed: int = 12


class CloseoutConfig(BaseModel):
    """After dispatch: associates go home; a supervisor and a manager close
    the day (GTDR, truckfile, scrubs) and plan tomorrow (VET/VTO, aisle
    volume, task assignment with job rotation). Proposed timings."""

    #: The final truckfile is published at this minute (14:00) — but
    #: revisions keep arriving afterwards and must be re-checked.
    final_truckfile_minute: float = 900  # 15:00
    ferry_check_minutes_before_final: float = 30
    ferry_check_minutes_after_final: float = 60
    #: The manager's default end-of-shift review (re-plans if anything changed).
    manager_review_minute: float = 1290  # 21:30
    build_plan_minute: float = 1080  # 18:00
    supervisor_end_minute: float = 1350  # 22:30
    gtdr_minutes: float = 6
    gtdr_drafted_minutes: float = 2
    ferry_check_minutes: float = 4
    in_station_scrub_minutes: float = 45
    on_road_scrub_minutes: float = 30
    outbound_pallet_truck_after_minutes: float = 90
    #: Tomorrow's roster and VET/VTO behaviour (associates choose; proposed rates).
    roster_size: int = 24
    vet_pool: int = 20
    vet_accept_rate: float = Field(0.5, ge=0, le=1)
    vto_accept_rate: float = Field(0.65, ge=0, le=1)
    vet_response_mean_minutes: float = 60
    target_spr: float = 150
    #: Headcount buffer over pure rate arithmetic (breaks, ramp-up, skill mix).
    planning_buffer: float = 1.2
    induct_window_hours: float = 6.5
    #: Job-rotation rule: at most this many consecutive days in the same role.
    max_consecutive_same_role: int = 2


class WorkGroup(BaseModel):
    """A crew with a shift window (as on a shift plan). `paths` are the
    process paths the group staffs; `scheduled` is headcount on the roster."""

    name: str
    start_minute: float
    end_minute: float
    attendance_rate: float = Field(0.92, ge=0, le=1)
    paths: list[str] = []


#: Process paths (generic names). `group` = labour group; `rate` = units per
#: labour hour (proposed); `driver` = which volume flows through it; `fixed`
#: = headcount per running line/finger/hour regardless of volume.
PROCESS_PATHS: dict[str, dict] = {
    "container_building": {
        "group": "Sort",
        "rate": 900,
        "driver": "auto_induct",
        "label": "Container building (auto-divert)",
    },
    "auto_induct_loader": {
        "group": "Sort",
        "rate": 1250,
        "driver": "auto_induct",
        "label": "Auto-scan induct loader",
    },
    "inbound_dock_ws": {
        "group": "Sort",
        "rate": 2200,
        "driver": "receive",
        "label": "Inbound dock water spider",
    },
    "induct": {
        "group": "Sort",
        "rate": 1000,
        "driver": "manual_induct",
        "label": "Induct (manual)",
    },
    "labeler": {"group": "Sort", "rate": 1250, "driver": "auto_induct", "label": "Labeler"},
    "pusher": {
        "group": "Sort",
        "rate": 0,
        "fixed": 1.0,
        "driver": "auto_line",
        "label": "Pusher / diverter",
    },
    "non_con_handling": {
        "group": "Sort",
        "rate": 400,
        "driver": "noncon",
        "label": "Non-con manual handling",
    },
    "sort_problem_solve": {
        "group": "Sort",
        "rate": 2600,
        "driver": "induct",
        "label": "Sort problem solve",
    },
    "stow": {"group": "Sort", "rate": 220, "driver": "stow", "label": "Stow"},
    "pick": {"group": "Pick Stage", "rate": 420, "driver": "pick", "label": "Pick & stage – pick"},
    "pick_stage_problem_solve": {
        "group": "Pick Stage",
        "rate": 5000,
        "driver": "pick",
        "label": "Pick-stage problem solve",
    },
    "yard_assist_cart": {
        "group": "Pick Stage",
        "rate": 2800,
        "driver": "pick",
        "label": "Yard assist & cart handling",
    },
    "yard_marshal": {
        "group": "UTR",
        "rate": 0,
        "fixed": 1.0,
        "driver": "yard",
        "label": "Yard marshal",
    },
    "high_value": {
        "group": "Site Support",
        "rate": 120,
        "driver": "hv",
        "label": "High-value cage",
    },
    "rts": {"group": "RTS", "rate": 90, "driver": "rts", "label": "Returns to station"},
}

#: Paths that carry ergonomic load; repeated days make them "disallowed" (proposed).
HEAVY_PATHS = ("stow", "container_building", "auto_induct_loader", "induct", "non_con_handling")


class LaborPlanConfig(BaseModel):
    """Work groups, VET/VTO opportunities and rotation (ADR-0016, proposed)."""

    work_groups: list[WorkGroup] = [
        WorkGroup(name="RTS", start_minute=90, end_minute=330, attendance_rate=1.0, paths=["rts"]),
        WorkGroup(
            name="Single Cycle (early)",
            start_minute=90,
            end_minute=330,
            attendance_rate=0.93,
            paths=["inbound_dock_ws", "container_building"],
        ),
        WorkGroup(
            name="Single Cycle",
            start_minute=150,
            end_minute=780,
            attendance_rate=0.9,
            paths=[
                "auto_induct_loader",
                "labeler",
                "pusher",
                "container_building",
                "induct",
                "non_con_handling",
                "sort_problem_solve",
                "stow",
                "pick",
                "high_value",
            ],
        ),
        WorkGroup(
            name="OTR Support",
            start_minute=480,
            end_minute=810,
            attendance_rate=1.0,
            paths=["yard_marshal", "yard_assist_cart"],
        ),
        WorkGroup(
            name="Single Cycle (late)",
            start_minute=540,
            end_minute=780,
            attendance_rate=0.8,
            paths=["pick", "pick_stage_problem_solve"],
        ),
        WorkGroup(
            name="Next Day Pick",
            start_minute=540,
            end_minute=780,
            attendance_rate=1.0,
            paths=["pick"],
        ),
    ]
    #: VET/VTO opportunities: associates submit during a sign-up window; the
    #: station accepts up to need (proposed behaviour, Q9).
    signup_window_minutes: float = 180
    #: Base share of eligible associates who submit to an open opportunity at
    #: 12+ h lead time; falls with shorter lead (proposed).
    vet_submit_rate: float = Field(0.45, ge=0, le=1)
    vto_submit_rate: float = Field(0.6, ge=0, le=1)
    acceptance_rule: Literal["first_come", "rotation_aware"] = "rotation_aware"
    #: Rotation: a heavy path on >= this many of the last 3 days is disallowed.
    heavy_days_disallow: int = 2


class TargetsConfig(BaseModel):
    """Proposed targets — configurable assumptions, not known standards."""

    dea: float = 0.99
    otd: float = 0.98
    sort_compliance: float = 0.99
    timely_staged: float = 0.98
    scan_compliance: float = 0.98
    hv_custody: float = 1.0
    swipe_compliance: float = 0.98


class StationOpsConfig(BaseModel):
    name: str = "normal_day"
    description: str = ""
    seed: int = 1
    ofd_date: date = date(2026, 1, 1)
    station_code: str = "NOVA-1"
    linehauls: list[LinehaulPlan] = []
    disruptions: list[Disruption] = []
    doors: int = 4
    unload_minutes_per_1000: float = 18
    induct: InductConfig = InductConfig()
    sort: SortConfig = SortConfig()
    stow: StowConfig = StowConfig()
    quality: QualityConfig = QualityConfig()
    labor: LaborConfig = LaborConfig()
    cycle: CycleConfig = CycleConfig()
    dispatch: DispatchConfig = DispatchConfig()
    outbound: OutboundConfig = OutboundConfig()
    backlog: BacklogConfig = BacklogConfig()
    targets: TargetsConfig = TargetsConfig()
    closeout: CloseoutConfig = CloseoutConfig()
    settings: SettingsConfig = SettingsConfig()
    labor_plan: LaborPlanConfig = LaborPlanConfig()
    #: Dock crew starts unloading the yard this long before induct starts.
    unload_lead_minutes: float = 30
    #: Volume scale multiplier applied by presets (site profile, Q2).
    scale: float = 1.0
    #: Work items still open at the end of the previous day (carry-over).
    carried_work_items: list[dict] = []
    source: Literal["synthetic_plan", "truckfile", "next_day"] = "synthetic_plan"
    #: 1 for a fresh day; +1 each time a day is continued from its close-out.
    day: int = 1
    #: Truckfile version the day was simulated from (next-day chains only).
    truckfile_version: int | None = None
    #: Agents' belief futures re-draw unknown driver behaviour with another
    #: seed, and pin what is already known (drivers who left, suspected
    #: no-shows) via overrides keyed by route index.
    driver_seed: str | None = None
    driver_overrides: dict[int, dict] = {}
    #: Floor behaviour already observed (misstage / forgotten bag), pinned in
    #: belief futures by route index; everything else is resampled.
    route_overrides: dict[int, dict] = {}

    @property
    def planned_volume(self) -> int:
        return sum(t.volume for t in self.linehauls)
