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
    rate_pph_per_line: float = 1100
    start_minute: float = 120  # 02:00
    no_read_rate: float = Field(0.012, ge=0, le=1)
    multi_read_rate: float = Field(0.004, ge=0, le=1)
    #: Sort-address label misapplied → relabel at problem solve.
    misapplied_label_rate: float = Field(0.003, ge=0, le=1)
    outages: list[InductOutage] = []


class SortConfig(BaseModel):
    missort_rate: float = Field(0.008, ge=0, le=1)
    #: Share of missorts caught & corrected at stow; the rest are left behind.
    missort_catch_rate: float = Field(0.7, ge=0, le=1)
    aisles_per_cluster: int = 20
    clusters: list[str] = ["A", "B"]
    #: Bay capacity headroom over the aisle's expected volume; overflow → jackpot.
    bay_headroom: float = 1.15


class StowConfig(BaseModel):
    stowers: int = 10
    rate_pph_per_stower: float = 220
    wip_target_min: float = 0.5
    wip_target_max: float = 10
    wip_compliance_target: float = 0.70


class QualityConfig(BaseModel):
    high_value_rate: float = Field(0.012, ge=0, le=1)
    unmanifested_rate: float = Field(0.02, ge=0, le=1)
    damaged_rate: float = Field(0.001, ge=0, le=1)
    damaged_unrecoverable_share: float = Field(0.5, ge=0, le=1)
    hv_scan_in_seconds: float = 45
    hv_handoff_seconds: float = 40


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


class CycleConfig(BaseModel):
    name: str = "CYCLE_1"
    #: Once pick starts, induct into the cycle is blocked; un-stowed volume rolls over.
    pick_start_minute: float = 510  # 08:30


class DspConfig(BaseModel):
    code: str
    #: Probability a driver of this DSP leaves late on a given day.
    late_rate: float
    standby_drivers: int = 1


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
    load_minutes: float = 10
    standby_lead_minutes: float = 30
    drive_speed_kmh: float = 35
    #: OTD tolerance — a proposed assumption, not a known org standard.
    otd_tolerance_minutes: float = 0
    swipe_forget_rate: float = Field(0.15, ge=0, le=1)
    delivery_failure_rate: float = Field(0.015, ge=0, le=1)
    customer_return_rate: float = Field(0.02, ge=0, le=1)


class OutboundConfig(BaseModel):
    routes: int = 80
    wave_stage_by_minutes: list[float] = [560, 580, 600, 620, 640]  # 09:20..10:40
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


class BacklogConfig(BaseModel):
    """Carry-over packages from previous days (ageing), as a share of volume."""

    rollover_share: float = 0.015
    retained: int = 90
    marked_missing: int = 40
    on_road_unconfirmed: int = 12


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
    source: Literal["synthetic_plan", "truckfile"] = "synthetic_plan"
    #: Agents' belief futures re-draw unknown driver behaviour with another
    #: seed, and pin what is already known (drivers who left, suspected
    #: no-shows) via overrides keyed by route index.
    driver_seed: str | None = None
    driver_overrides: dict[int, dict] = {}

    @property
    def planned_volume(self) -> int:
        return sum(t.volume for t in self.linehauls)
