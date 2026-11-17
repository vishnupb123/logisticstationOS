"""Deterministic risk detectors, grouped by the specialist agent that owns
them. Rule-based by design (same stance as app/security/policy_engine.py):
each detector states its arithmetic, so its output is auditable.

Information discipline (realism): detectors only use what the station could
know at the current minute — the *revealed* ferry ETA (not the true delay),
a driver's planned check-in until they have actually left, a no-show only
once the driver is overdue and unresponsive. Never the twin's hidden future.

Evidence categories: read straight off state = `observation`; a computed
ratio = `calculated`; a forward projection = `prediction`; a judgement from
indirect signals (e.g. a likely no-show) = `inferred`.
"""

from typing import Literal

from pydantic import BaseModel

from app.agents.schemas import EvidenceCategory
from app.simulation.station_ops.model import StationOpsTwin, clock, sector_of
from app.simulation.station_ops.snapshot import StationOpsSnapshot


def twin_sector(d) -> str:
    return sector_of(*d.home)


AgentName = Literal["inbound", "sort_stow", "outbound", "dispatch", "quality", "planning"]

RiskType = Literal[
    "late_linehaul_rollover",
    "yard_congestion",
    "induct_capacity_shortfall",
    "stow_capacity_shortfall",
    "induct_line_down",
    "stow_wip_above_band",
    "stow_wip_below_band",
    "problem_solve_backlog",
    "routes_at_risk",
    "driver_late",
    "driver_no_show",
    "pending_swipe",
    "wave_checkin_upcoming",
    "traffic_incident",
    "hv_backlog",
    "sort_compliance_below_target",
    "scan_compliance_below_target",
    "cart_misstaged",
    "bag_left_in_aisle",
    "van_grounded",
    "vsa_queue",
    "truckfile_changed_since_plan",
    "next_day_staffing_gap",
    "ferry_check_due",
    "gtdr_open",
    # v2
    "induct_below_dynamic_target",
    "belt_gap_lost_hours",
    "finger_full_bay",
    "automation_no_read_spike",
    "induct_dwell_over_60",
    "pending_reinduct_at_risk",
    "network_missort_backlog",
    "unplanned_surge",
    "unload_sequence_conflict",
    "container_stuck",
    "damaged_pending_approval",
    "late_volume_at_pick_start",
    "opportunity_window_closing",
    "rotation_violation",
]

OWNER: dict[str, AgentName] = {
    "late_linehaul_rollover": "inbound",
    "yard_congestion": "inbound",
    "induct_capacity_shortfall": "sort_stow",
    "stow_capacity_shortfall": "sort_stow",
    "induct_line_down": "sort_stow",
    "stow_wip_above_band": "sort_stow",
    "stow_wip_below_band": "sort_stow",
    "problem_solve_backlog": "sort_stow",
    "routes_at_risk": "outbound",
    "driver_late": "dispatch",
    "driver_no_show": "dispatch",
    "pending_swipe": "dispatch",
    "wave_checkin_upcoming": "dispatch",
    "traffic_incident": "dispatch",
    "hv_backlog": "quality",
    "sort_compliance_below_target": "quality",
    "scan_compliance_below_target": "quality",
    "cart_misstaged": "outbound",
    "bag_left_in_aisle": "outbound",
    "van_grounded": "dispatch",
    "vsa_queue": "dispatch",
    "truckfile_changed_since_plan": "planning",
    "next_day_staffing_gap": "planning",
    "ferry_check_due": "planning",
    "gtdr_open": "planning",
    "induct_below_dynamic_target": "sort_stow",
    "belt_gap_lost_hours": "sort_stow",
    "finger_full_bay": "sort_stow",
    "automation_no_read_spike": "quality",
    "induct_dwell_over_60": "sort_stow",
    "pending_reinduct_at_risk": "sort_stow",
    "network_missort_backlog": "quality",
    "unplanned_surge": "inbound",
    "unload_sequence_conflict": "inbound",
    "container_stuck": "inbound",
    "damaged_pending_approval": "quality",
    "late_volume_at_pick_start": "outbound",
    "opportunity_window_closing": "planning",
    "rotation_violation": "planning",
}

AGENT_LABEL: dict[str, str] = {
    "inbound": "Inbound Agent",
    "sort_stow": "Sort & Stow Agent",
    "outbound": "Outbound Agent",
    "dispatch": "Dispatch Agent",
    "quality": "Quality & HV Agent",
    "planning": "Shift Planning Agent",
}


class Risk(BaseModel):
    risk_type: RiskType
    agent: AgentName | None = None
    severity: Literal["info", "warning", "critical"]
    category: EvidenceCategory
    summary: str
    metric: Literal[
        "dea",
        "otd",
        "timely_staged",
        "sort_compliance",
        "scan_compliance",
        "labor",
        "hv_custody",
        "swipe_compliance",
        "next_day_readiness",
    ]
    projected_impact: int
    detected_at_minute: float
    evidence: dict

    def model_post_init(self, __context) -> None:
        if self.agent is None:
            self.agent = OWNER[self.risk_type]


def _staffed_lines(twin: StationOpsTwin) -> set[int]:
    lines = {a.line for a in twin.assocs if a.present and a.role == "induct" and a.line}
    if not lines and twin.now_minute < twin.config.induct.start_minute:
        lines = set(range(1, twin.total_lines() + 1))
    return lines


def observed_induct_factor(twin: StationOpsTwin) -> float:
    """Online capacity learning: when induct has had a standing queue for the
    last hour, its trailing throughput *is* its real capacity (skill mix,
    rework, small stoppages) — use that instead of the nameplate rate. With
    no standing queue the observation is demand-limited, so keep nameplate."""
    c = twin.config.induct
    if twin.now_minute < c.start_minute + 60 or len(twin.induct_q) < 150:
        return 1.0
    lines = max(1, len(_staffed_lines(twin)))
    observed = twin.rate_last_hour(twin._inducted_times)  # inducted in the trailing hour
    nominal = sum(twin.line_rate(ln) for ln in _staffed_lines(twin)) or lines * c.rate_pph_per_line
    return max(0.5, min(1.0, observed / nominal)) if observed else 1.0


def induct_capacity(twin: StationOpsTwin, start: float, end: float) -> float:
    """Packages the staffed induct lines can process in [start, end] minutes,
    net of *known* down time (planned outages + jams already under way),
    scaled by the throughput actually observed (`observed_induct_factor`)."""
    factor = observed_induct_factor(twin)
    total = 0.0
    for line in _staffed_lines(twin):
        per_line = twin.line_rate(line) / 60 * factor
        minutes = twin.belt_run_minutes(start, end)
        for ln, s, e, why in twin.line_down_windows:
            known = why == "planned" or s / 60 <= twin.now_minute
            if ln == line and known:
                minutes -= max(0.0, min(end, e / 60) - max(start, s / 60))
        total += max(0.0, minutes) * per_line
    return total


def stow_rate_per_min(twin: StationOpsTwin) -> float:
    present = sum(1 for a in twin.assocs if a.present and a.role == "stow")
    nominal = present * twin.config.stow.rate_pph_per_stower / 60
    if (
        len(twin.stow_q) > 100
        and twin.now_minute >= twin.config.induct.start_minute + 60
        and present
    ):
        observed = twin.rate_last_hour(twin._stowed_times) / 60  # standing queue: real capacity
        if observed:
            return max(0.5 * nominal, min(nominal, observed))
    return nominal


def detect_risks(twin: StationOpsTwin, snap: StationOpsSnapshot) -> list[Risk]:  # noqa: C901
    c = twin.config
    now = twin.now_minute
    cutoff = twin.cutoff / 60
    risks: list[Risk] = []
    ps = snap.package_status

    def add(**kw) -> None:
        risks.append(Risk(detected_at_minute=now, **kw))

    if not twin.pick_started:
        start = max(now, c.induct.start_minute)
        minutes_left = max(0.0, cutoff - start)
        n_lines = max(1, len(_staffed_lines(twin)))
        induct_rate = (
            sum(twin.line_rate(ln) for ln in _staffed_lines(twin))
            / 60
            * observed_induct_factor(twin)
        ) or n_lines * c.induct.rate_pph_per_line / 60

        # --- inbound agent ---------------------------------------------------
        late = []
        for i, plan in enumerate(c.linehauls):
            if twin.trips[i].status != "in_transit" or plan.cancelled:
                continue
            known = plan.known_delay(now)
            eta = plan.planned_arrival_minute + known
            unload = plan.volume / 1000 * c.unload_minutes_per_1000
            ready_by = eta + unload + plan.volume / max(induct_rate, 1e-6)
            if known > 0 and ready_by > cutoff:
                late.append((plan, eta, ready_by))
        if late:
            volume = sum(p.volume for p, _, _ in late)
            trips = ", ".join(
                f"{p.trip_id} {p.origin}{' ferry' if p.via_ferry else ''} ETA {clock(e)}"
                for p, e, _ in late
            )
            add(
                risk_type="late_linehaul_rollover",
                severity="critical",
                category=EvidenceCategory.PREDICTION,
                metric="dea",
                projected_impact=volume,
                summary=f"{len(late)} delayed linehaul(s) ({volume} pkgs) projected to finish "
                f"induct after pick start {clock(cutoff)}: {trips}. Unhandled, this volume "
                "rolls over.",
                evidence={
                    "trips": [
                        {
                            "trip_id": p.trip_id,
                            "eta": clock(e),
                            "ready_by": clock(r),
                            "known_delay": p.known_delay(now),
                        }
                        for p, e, r in late
                    ],
                    "pick_start": clock(cutoff),
                },
            )
        if len(twin.yard) >= 2:
            waiting = [c.linehauls[t] for t in twin.yard]
            add(
                risk_type="yard_congestion",
                severity="warning",
                category=EvidenceCategory.OBSERVATION,
                metric="dea",
                projected_impact=sum(p.volume for p in waiting),
                summary=f"{len(waiting)} trailer(s) waiting in the yard for a door "
                f"({', '.join(p.trip_id for p in waiting)}) — the unload sequence decides what "
                "makes the cycle.",
                evidence={"yard": [p.trip_id for p in waiting]},
            )

        # --- sort & stow agent -------------------------------------------------
        arriving = sum(
            plan.volume
            for i, plan in enumerate(c.linehauls)
            if twin.trips[i].status in ("in_transit", "in_yard")
            and not plan.cancelled
            and plan.planned_arrival_minute + plan.known_delay(now) < cutoff
        )
        induct_work = ps["pending_induct"] + ps["problem_solve"] + arriving
        cap = induct_capacity(twin, start, cutoff)
        short = int(induct_work - cap)
        if short > 50:
            add(
                risk_type="induct_capacity_shortfall",
                severity="critical" if short > 500 else "warning",
                category=EvidenceCategory.PREDICTION,
                metric="dea",
                projected_impact=short,
                summary=f"Induct backlog + inbound before pick start = {induct_work} pkgs vs "
                f"capacity {int(cap)} ({n_lines} staffed line(s), net of known down time): "
                f"~{short} pkgs projected to roll over.",
                evidence={"induct_work": induct_work, "induct_capacity": int(cap)},
            )

        stow_work = (
            ps["pending_stow"]
            + ps["stowing"]
            + ps.get("stow_buffered", 0)
            + min(induct_work, int(cap))
        )
        minutes_left = twin.belt_run_minutes(start, cutoff) + c.stow.drain_minutes
        incoming = sum(
            1 for a in twin.assocs if a.vet and a.role == "stow" and a.shift_start > twin.env.now
        )
        vet_cap = (
            sum(
                max(0.0, cutoff - a.shift_start / 60)
                for a in twin.assocs
                if a.vet and a.role == "stow" and a.shift_start > twin.env.now
            )
            * c.stow.rate_pph_per_stower
            / 60
        )
        stow_cap = stow_rate_per_min(twin) * minutes_left + vet_cap
        stow_short = int(stow_work - stow_cap)
        if stow_short > 50 and now >= c.induct.start_minute:
            add(
                risk_type="stow_capacity_shortfall",
                severity="critical" if stow_short > 500 else "warning",
                category=EvidenceCategory.PREDICTION,
                metric="dea",
                projected_impact=stow_short,
                summary=f"Stow demand to pick start = {stow_work} pkgs vs capacity {int(stow_cap)} "
                f"({snap.stow['stowers']} stowers + {incoming} VET en route): ~{stow_short} pkgs "
                "projected unstowed at pick start.",
                evidence={"stow_work": stow_work, "stow_capacity": int(stow_cap)},
            )

        down = snap.induct["down_lines"]
        if down:
            add(
                risk_type="induct_line_down",
                severity="critical",
                category=EvidenceCategory.OBSERVATION,
                metric="dea",
                projected_impact=int(sum(twin.line_rate(x) for x in down)),
                summary=f"Induct line(s) {', '.join(twin.line_name(x) for x in down)} down "
                f"(lost hours so far {snap.metrics['lost_hours'].value}h).",
                evidence={"lines": down},
            )

        # Stow WIP (documented): (INC ÷ Stow FPH) × 60 against the Settings band
        wip = snap.stow["wip_minutes"]
        lo, hi = c.settings.stow_wip_lower_min, c.settings.stow_wip_upper_min
        settled = (
            now >= c.induct.start_minute + c.settings.fast_start_minutes + 30
            and not twin.in_break()
            and not twin.in_break(twin.env.now - c.settings.induct_fph_window_minutes * 60)
        )
        if settled and snap.stow["stowers"] and wip < 999:
            if wip > hi * 1.15:
                add(
                    risk_type="stow_wip_above_band",
                    severity="warning",
                    category=EvidenceCategory.CALCULATED,
                    metric="dea",
                    projected_impact=snap.stow["wip_packages"],
                    summary=f"Stow WIP {wip:.0f} min (INC {snap.stow['wip_packages']} ÷ Stow FPH "
                    f"{snap.stow['stow_fph']} × 60) is above the {lo:.0f}–{hi:.0f} min band — stow "
                    "is the bottleneck.",
                    evidence={"wip_minutes": wip, "band": [lo, hi]},
                )
            elif wip < lo * 0.6 and snap.induct["queue"] < 50 and now < cutoff - 60:
                add(
                    risk_type="stow_wip_below_band",
                    severity="info",
                    category=EvidenceCategory.CALCULATED,
                    metric="labor",
                    projected_impact=snap.stow["stowers"],
                    summary=f"Stow WIP {wip:.1f} min is below the {lo:.0f}–{hi:.0f} min band — "
                    "stowers are starved; labor could help problem solve or the HV cage.",
                    evidence={"wip_minutes": wip, "band": [lo, hi]},
                )

        risks += _sort_v2(twin, snap, now, cutoff)

        pq = snap.induct["problem_queue"]
        if pq > 40:
            add(
                risk_type="problem_solve_backlog",
                severity="warning",
                category=EvidenceCategory.OBSERVATION,
                metric="dea",
                projected_impact=pq,
                summary=f"{pq} packages waiting at problem solve — each rolls over if not "
                "re-inducted before pick start.",
                evidence={"queue": pq},
            )

    # --- outbound agent ---------------------------------------------------------
    at_risk = [r for r in snap.routes if r["at_risk"] and r["status"] in ("not_ready", "ready")]
    if at_risk:
        examples = ", ".join(
            f"{r['route_id']} by {r['stage_by']} → {r['projected_stage_at']}" for r in at_risk[:3]
        )
        add(
            risk_type="routes_at_risk",
            severity="critical" if len(at_risk) > 5 else "warning",
            category=EvidenceCategory.PREDICTION,
            metric="timely_staged",
            projected_impact=len(at_risk),
            summary=f"{len(at_risk)} route(s) projected to stage after stage-by ({examples}).",
            evidence={"routes": [r["route_id"] for r in at_risk]},
        )

    # --- dispatch agent ----------------------------------------------------------
    no_show, late_d = [], []
    for d in twin.drivers:
        if d.state not in ("off_duty", "en_route") or d.standby:
            continue
        r = twin.routes[d.route]
        if r.departed_at is not None or r.driver != d.idx:
            continue
        overdue = d.leave_at is None and twin.env.now > twin.planned_leave(d) + 15 * 60
        if overdue and d.notified_at is not None and twin.env.now > d.notified_at + 15 * 60:
            no_show.append((r, d))
        elif overdue or twin.driver_late_by(d) > 3:
            late_d.append((r, d, max(twin.driver_late_by(d), 15 if overdue else 0)))
    if late_d:
        add(
            risk_type="driver_late",
            severity="warning",
            category=EvidenceCategory.PREDICTION,
            metric="otd",
            projected_impact=len(late_d),
            summary=f"{len(late_d)} driver(s) projected late for check-in: "
            + ", ".join(
                f"{d.driver_id} ({d.dsp}, {r.route_id}) +{m:.0f} min" for r, d, m in late_d[:4]
            ),
            evidence={
                "routes": [r.route_id for r, _, _ in late_d],
                "unnotified": [r.route_id for r, d, _ in late_d if d.notified_at is None],
            },
        )
    if no_show:
        add(
            risk_type="driver_no_show",
            severity="critical",
            category=EvidenceCategory.INFERRED,
            metric="otd",
            projected_impact=len(no_show),
            summary="Driver(s) overdue and unresponsive after notification: "
            + ", ".join(f"{d.driver_id} ({d.dsp}) for {r.route_id}" for r, d in no_show)
            + " — likely no-show.",
            evidence={"routes": [r.route_id for r, _ in no_show]},
        )
    # Proactive: drivers due to leave for check-in within the next 40 min who
    # haven't had a reminder — the cheapest OTD lever there is.
    upcoming = [
        twin.routes[d.route].route_id
        for d in twin.drivers
        if d.state == "off_duty"
        and not d.standby
        and d.notified_at is None
        and twin.routes[d.route].driver == d.idx
        and twin.env.now <= twin.planned_leave(d) <= twin.env.now + 40 * 60
    ]
    if upcoming:
        add(
            risk_type="wave_checkin_upcoming",
            severity="info",
            category=EvidenceCategory.OBSERVATION,
            metric="otd",
            projected_impact=len(upcoming),
            summary=f"{len(upcoming)} driver(s) due to set off for check-in within 40 min — "
            "sending wave reminders.",
            evidence={"unnotified": upcoming},
        )
    for inc in twin.disruptions_seen:
        if inc["kind"] != "traffic_incident" or inc["to"] <= twin.env.now:
            continue
        exposed = sum(
            1
            for d in twin.drivers
            if d.state == "off_duty"
            and d.leave_at is None
            and (inc["target"] in (None, "ALL") or twin_sector(d) == inc["target"])
        )
        if exposed:
            add(
                risk_type="traffic_incident",
                severity="warning",
                category=EvidenceCategory.OBSERVATION,
                metric="otd",
                projected_impact=exposed,
                summary=f"Traffic incident in sector {inc['target']} (+{inc['magnitude']:.0f} min) "
                f"with {exposed} driver(s) yet to set off — reroute / leave early.",
                evidence={"sector": inc["target"], "minutes": inc["magnitude"]},
            )
    very_late = [
        twin.routes[d.route].route_id
        for d in twin.drivers
        if d.state in ("off_duty", "en_route")
        and not d.standby
        and twin.routes[d.route].driver == d.idx
        and twin.routes[d.route].departed_at is None
        and twin.driver_late_by(d) > twin.config.dispatch.standby_lead_minutes + 10
        and twin.standby_remaining.get(d.dsp, 0) > 0
    ]
    if very_late:
        add(
            risk_type="driver_no_show",
            severity="critical",
            category=EvidenceCategory.PREDICTION,
            metric="otd",
            projected_impact=len(very_late),
            summary="Driver(s) projected later than a standby could arrive: "
            + ", ".join(very_late)
            + " — standby reassignment beats waiting.",
            evidence={"routes": very_late},
        )
    pending_swipe = sum(
        1
        for d in twin.drivers
        if d.return_at and d.return_at <= twin.env.now and d.swiped_at is None
    )
    if pending_swipe:
        add(
            risk_type="pending_swipe",
            severity="info",
            category=EvidenceCategory.OBSERVATION,
            metric="swipe_compliance",
            projected_impact=pending_swipe,
            summary=f"{pending_swipe} returned driver(s) haven't swiped to finish.",
            evidence={"count": pending_swipe},
        )

    # --- quality & HV agent ------------------------------------------------------
    if len(twin.hv_q) > 15:
        hv_assoc = sum(1 for a in twin.assocs if a.present and a.role == "high_value")
        add(
            risk_type="hv_backlog",
            severity="warning",
            category=EvidenceCategory.OBSERVATION,
            metric="hv_custody",
            projected_impact=len(twin.hv_q),
            summary=f"{len(twin.hv_q)} high-value tasks queued at the cage with {hv_assoc} HV "
            "associate(s) — route staging waits on HV handoffs.",
            evidence={"queue": len(twin.hv_q)},
        )
    sc = snap.metrics["sort_compliance"].value
    if sc is not None and snap.sort["sorted"] >= 500 and sc < c.targets.sort_compliance:
        add(
            risk_type="sort_compliance_below_target",
            severity="warning",
            category=EvidenceCategory.CALCULATED,
            metric="sort_compliance",
            projected_impact=snap.sort["missorts"],
            summary=f"Sort compliance {sc:.2%} below target {c.targets.sort_compliance:.1%} "
            f"({snap.sort['missorts']} missorts).",
            evidence={"missorts": snap.sort["missorts"]},
        )
    scan = snap.metrics["scan_compliance"].value
    if scan is not None and snap.induct["attempts"] >= 500 and scan < c.targets.scan_compliance:
        add(
            risk_type="scan_compliance_below_target",
            severity="warning",
            category=EvidenceCategory.CALCULATED,
            metric="scan_compliance",
            projected_impact=snap.induct["no_reads"] + snap.induct["multi_reads"],
            summary=f"Scan compliance {scan:.2%} below target {c.targets.scan_compliance:.0%} "
            f"(no-reads {snap.induct['no_reads']}, multi-reads {snap.induct['multi_reads']}, "
            f"misapplied labels {snap.induct['misapplied_labels']}).",
            evidence={"no_reads": snap.induct["no_reads"]},
        )
    risks.extend(_floor_and_yard(twin, now))
    risks.extend(_floor_v2(twin, now))
    risks.extend(_closeout(twin, now))
    return risks


def _floor_and_yard(twin: StationOpsTwin, now: float) -> list[Risk]:
    """Sudden floor / yard events — each flagged by a scan or an audit the
    moment it happens, so detecting them uses no hidden information."""
    out: list[Risk] = []
    mis = [
        r
        for r in twin.routes
        if r.misstaged_at is not None and r.misstage_fixed_at is None and not r.restaging
    ]
    if mis:
        out.append(
            Risk(
                risk_type="cart_misstaged",
                severity="critical",
                category=EvidenceCategory.OBSERVATION,
                metric="otd",
                projected_impact=len(mis),
                detected_at_minute=now,
                summary="Wrong staging scan: "
                + ", ".join(
                    f"{r.route_id} cart in {r.misstaged_at} (belongs {r.staging_location}, "
                    f"{(twin.env.now - r.misstaged_since) / 60:.0f} min)"
                    for r in mis
                )
                + " — route can't load; neighbour location obstructed.",
                evidence={"routes": [r.route_id for r in mis]},
            )
        )
    bags = {}
    for p in twin.pkgs:
        if p.status == "left_behind" and p.left_reason == "bag_not_loaded":
            r = twin.routes[p.route]
            if r.departed_at is None and r.aisle not in twin.sweeping:
                bags.setdefault(r.route_id, (r, 0))
                bags[r.route_id] = (r, bags[r.route_id][1] + 1)
    pending = [(r, n) for r, n in bags.values() if r.aisle not in twin.sweep_priority]
    if pending:
        out.append(
            Risk(
                risk_type="bag_left_in_aisle",
                severity="warning",
                category=EvidenceCategory.OBSERVATION,
                metric="dea",
                projected_impact=sum(n for _, n in pending),
                detected_at_minute=now,
                summary="Bag picked but not scanned to cart: "
                + ", ".join(
                    f"{r.route_id} ({n} pkgs, aisle {r.aisle}, departs "
                    f"{clock(r.planned_depart / 60)})"
                    for r, n in pending
                )
                + " — sweep before the van leaves or it becomes a cluster transfer.",
                evidence={"aisles": sorted({r.aisle for r, _ in pending})},
            )
        )
    grounded = [d for d in twin.drivers if d.state == "grounded" and d.van_request is None]
    if grounded:
        out.append(
            Risk(
                risk_type="van_grounded",
                severity="critical",
                category=EvidenceCategory.OBSERVATION,
                metric="otd",
                projected_impact=len(grounded),
                detected_at_minute=now,
                summary="Van(s) grounded at VSA with no replacement requested: "
                + ", ".join(
                    f"{twin.routes[d.route].route_id} ({d.dsp}, {d.vsa_defect})" for d in grounded
                ),
                evidence={"routes": [twin.routes[d.route].route_id for d in grounded]},
            )
        )
    backlog = max(twin._marshal_free) - twin.env.now if twin._marshal_free else 0
    waiting = sum(1 for d in twin.drivers if d.state == "vsa")
    if backlog > 6 * 60 and waiting >= 4 and not twin.departures_done:
        out.append(
            Risk(
                risk_type="vsa_queue",
                severity="warning",
                category=EvidenceCategory.CALCULATED,
                metric="otd",
                projected_impact=waiting,
                detected_at_minute=now,
                summary=f"{waiting} van(s) queued for VSA; marshals booked "
                f"{backlog / 60:.0f} min ahead — loading will slip.",
                evidence={"waiting": waiting, "backlog_minutes": round(backlog / 60, 1)},
            )
        )
    return out


def _sort_v2(
    twin: StationOpsTwin, snap: StationOpsSnapshot, now: float, cutoff: float
) -> list[Risk]:
    """v2 detectors built on the documented metrics (HANDOFF_V2 §9)."""
    c = twin.config
    out: list[Risk] = []
    m = snap.metrics

    def add(**kw) -> None:
        out.append(Risk(detected_at_minute=now, **kw))

    started = now >= c.induct.start_minute + c.settings.fast_start_minutes + 45
    fph, target = m["induct_fph"].value, m["induct_fph"].target
    if started and target and not twin.in_break() and fph is not None and fph < 0.85 * target:
        belt_h = m["belt_run_time"].value or 0
        add(
            risk_type="induct_below_dynamic_target",
            severity="warning",
            category=EvidenceCategory.CALCULATED,
            metric="dea",
            projected_impact=int((target - fph) * belt_h),
            summary=f"Induct FPH {fph:,.0f} is {1 - fph / target:.0%} under the target "
            f"{target:,.0f} (volume remaining {m['induct_fph'].inputs['volume_remaining']:,} ÷ "
            f"{belt_h} h of belt run time left).",
            evidence={"fph": fph, "target": target, "belt_hours_left": belt_h},
        )
    # belt gaps in the last hour per line (documented lost-hours rule)
    lo, hi = c.settings.belt_gap_defect_seconds
    worst = None
    for ln, times in twin._line_scan_times.items():
        recent = [t for t in times if t >= twin.env.now - 3600]
        lost = sum(b - a for a, b in zip(recent, recent[1:], strict=False) if lo < b - a < hi)
        if worst is None or lost > worst[1]:
            worst = (ln, lost)
    if started and worst and worst[1] > 0.2 * 3600:
        add(
            risk_type="belt_gap_lost_hours",
            severity="warning",
            category=EvidenceCategory.CALCULATED,
            metric="dea",
            projected_impact=int(worst[1] / 3600 * twin.line_rate(worst[0])),
            summary=f"{twin.line_name(worst[0])} lost {worst[1] / 60:.0f} min in the last hour to "
            f"belt gaps of {lo:.0f}–{hi:.0f} s (micro-stops).",
            evidence={"line": twin.line_name(worst[0]), "lost_minutes": round(worst[1] / 60, 1)},
        )
    cap = c.sort.finger_bay_capacity
    for finger, fs in twin.finger_stats.items():
        if fs["buffer"] >= 0.9 * cap and not twin.pick_started:
            add(
                risk_type="finger_full_bay",
                severity="warning",
                category=EvidenceCategory.OBSERVATION,
                metric="dea",
                projected_impact=fs["buffer"],
                summary=f"{finger} bays {fs['buffer']}/{cap} — at full bay new volume diverts to "
                "the jackpot.",
                evidence={"finger": finger, "buffer": fs["buffer"], "capacity": cap},
            )
    q = snap.induct.get("quality_by_line") or []
    for row in q:
        if (
            row["automated"]
            and row["no_read"]
            and row["attempts"] > 300
            and row["no_read"] > 2 * c.induct.no_read_rate
        ):
            add(
                risk_type="automation_no_read_spike",
                severity="warning",
                category=EvidenceCategory.CALCULATED,
                metric="scan_compliance",
                projected_impact=int(row["no_read"] * row["attempts"]),
                summary=f"No-read {row['no_read']:.1%} on {row['line']} (2× normal) — the top "
                "quality issue; every no-read is a problem-solve touch.",
                evidence={"line": row["line"], "no_read": row["no_read"]},
            )
    dwell = m["induct_dwell"].value or 0
    if dwell > 30:
        add(
            risk_type="induct_dwell_over_60",
            severity="warning",
            category=EvidenceCategory.OBSERVATION,
            metric="dea",
            projected_impact=dwell,
            summary=f"{dwell} package(s) neither inducted nor stowed for over 60 min "
            f"({m['induct_dwell'].inputs['by_cluster']}).",
            evidence=m["induct_dwell"].inputs,
        )
    pr = m["pending_reinduct"].value or 0
    if pr > 15:
        add(
            risk_type="pending_reinduct_at_risk",
            severity="warning",
            category=EvidenceCategory.PREDICTION,
            metric="dea",
            projected_impact=pr,
            summary=f"{pr} package(s) marked for reprocess inside the re-induct window — at "
            "risk of missing on-time re-induct.",
            evidence={"count": pr},
        )
    nm = m["network_missorts"].inputs
    if nm["pending_ps"] > 25:
        add(
            risk_type="network_missort_backlog",
            severity="info",
            category=EvidenceCategory.OBSERVATION,
            metric="sort_compliance",
            projected_impact=nm["pending_ps"],
            summary=f"{nm['pending_ps']} network missort(s) (wrong station / carrier) waiting for "
            "problem solve to re-plan them.",
            evidence=nm,
        )
    arrived = twin.counters["arrived"]
    unplanned = sum(1 for p in twin.pkgs if not p.planned and p.arrived_at is not None)
    expected = sum(
        t.volume * t.unplanned_share
        for i, t in enumerate(c.linehauls)
        if twin.trips[i].yard_at is not None
    )
    if arrived > 1500 and unplanned > 1.25 * expected + 200:
        add(
            risk_type="unplanned_surge",
            severity="warning",
            category=EvidenceCategory.CALCULATED,
            metric="dea",
            projected_impact=int(unplanned - expected),
            summary=f"Unplanned volume {unplanned:,} vs ~{expected:,.0f} expected from the "
            "manifests — sort and stow load is above plan.",
            evidence={"unplanned": unplanned, "expected": round(expected)},
        )
    open_at = c.induct.start_minute - c.unload_lead_minutes
    if now > open_at + 45 and len(twin.yard) >= 2:
        # an early-EAD / delayed (late-planned) trailer queued behind bulk
        waiting = sorted(twin.yard, key=lambda t: c.linehauls[t].planned_arrival_minute)
        late = [
            t
            for t in waiting
            if c.linehauls[t].known_delay(now) > 0 and twin.trips[t].priority == 0
        ]
        if late:
            t = late[0]
            add(
                risk_type="unload_sequence_conflict",
                severity="info",
                category=EvidenceCategory.OBSERVATION,
                metric="dea",
                projected_impact=c.linehauls[t].volume,
                summary=f"{c.linehauls[t].trip_id} (late, {c.linehauls[t].volume} pkgs) is queued "
                "behind other trailers — move it up the unload sequence.",
                evidence={"trip": c.linehauls[t].trip_id},
            )
    stuck = []
    for cont in twin.containers:
        if cont["unloaded_at"] is None or twin.env.now - cont["unloaded_at"] < 75 * 60:
            continue
        left = sum(1 for i in cont["pkgs"][:400] if twin.pkgs[i].status == "pending_induct")
        if left > 20:
            stuck.append((cont["id"], left))
    if stuck and not twin.pick_started:
        add(
            risk_type="container_stuck",
            severity="info",
            category=EvidenceCategory.OBSERVATION,
            metric="dea",
            projected_impact=sum(x[1] for x in stuck),
            summary=f"{len(stuck)} container(s) unloaded 75+ min ago still pending induct "
            f"({', '.join(f'{a} {b}' for a, b in stuck[:3])}).",
            evidence={"containers": stuck[:10]},
        )
    return out


def _floor_v2(twin: StationOpsTwin, now: float) -> list[Risk]:
    """Problem-solve approvals and the pick-start cycle decision."""
    c = twin.config
    out: list[Risk] = []
    pend = [p for p in twin.pkgs if p.ps_state == "pending_approval"]
    if pend and not twin.approve_fast:
        out.append(
            Risk(
                risk_type="damaged_pending_approval",
                severity="info",
                category=EvidenceCategory.OBSERVATION,
                metric="dea",
                projected_impact=len(pend),
                detected_at_minute=now,
                summary=f"{len(pend)} damaged package(s) waiting for manager review (pending "
                "approval) — they can't be repacked or re-inducted until approved.",
                evidence={"pending": len(pend)},
            )
        )
    cutoff = twin.cutoff / 60
    if not twin.pick_started and cutoff - 30 <= now < cutoff and twin.force_until is None:
        floor = sum(
            1
            for p in twin.pkgs
            if p.arrived_at is not None and p.status in ("pending_induct", "problem_solve")
        )
        if floor > 100:
            out.append(
                Risk(
                    risk_type="late_volume_at_pick_start",
                    severity="warning",
                    category=EvidenceCategory.PREDICTION,
                    metric="dea",
                    projected_impact=floor,
                    detected_at_minute=now,
                    summary=f"{floor} package(s) still waiting for induct {cutoff - now:.0f} min "
                    "before pick start — they will miss the cycle unless force-inducted or the "
                    "cut moves.",
                    evidence={"on_floor": floor, "phase": "before"},
                )
            )
    elif twin.pick_started and not twin.departures_done:
        on_floor = sum(
            1 for p in twin.pkgs if p.status == "rolled_over" and p.arrived_at is not None
        )
        if on_floor > 0 and not any(x["action"] == "change_cycle" for x in twin.cycle_changes):
            out.append(
                Risk(
                    risk_type="late_volume_at_pick_start",
                    severity="warning",
                    category=EvidenceCategory.OBSERVATION,
                    metric="dea",
                    projected_impact=on_floor,
                    detected_at_minute=now,
                    summary=f"Pick has started for {c.cycle.name}: {on_floor} package(s) on the "
                    "floor missed the cycle — change their cycle to tomorrow so they aren't held "
                    "as wrong-cycle, and enable the next cycle for late arrivals.",
                    evidence={"on_floor": on_floor, "phase": "after"},
                )
            )
    return out


def _closeout(twin: StationOpsTwin, now: float) -> list[Risk]:
    co = getattr(twin, "closeout", None)
    if co is None or co.started_at is None or co.complete:
        return []
    out: list[Risk] = []
    if co.final_published_at is not None:
        base = co.plan or co.headcount
        if (
            base
            and base["truckfile_version"] != co.truckfile_version
            and not co._has("manager", "replan")
        ):
            out.append(
                Risk(
                    risk_type="truckfile_changed_since_plan",
                    severity="critical",
                    category=EvidenceCategory.OBSERVATION,
                    metric="next_day_readiness",
                    projected_impact=co.truckfile_version - base["truckfile_version"],
                    detected_at_minute=now,
                    summary=f"Truckfile is at v{co.truckfile_version} but tomorrow's plan is on "
                    f"v{base['truckfile_version']} — volume/headcount may be wrong.",
                    evidence={"latest": co.truckfile_version, "plan": base["truckfile_version"]},
                )
            )
        if co.headcount:
            recs = co.opportunities.recommendations()
            if recs:
                total = sum(r["headcount"] * (1 if r["type"] == "VET" else -1) for r in recs)
                out.append(
                    Risk(
                        risk_type="next_day_staffing_gap",
                        severity="warning",
                        category=EvidenceCategory.PREDICTION,
                        metric="next_day_readiness",
                        projected_impact=sum(r["headcount"] for r in recs),
                        detected_at_minute=now,
                        summary="Tomorrow's labor plan is unbalanced by work group: "
                        + "; ".join(
                            f"{r['type']} {r['headcount']} HC for {r['frame']} ({r['time_frame']})"
                            for r in recs
                        )
                        + " (assuming no more acceptance of submitted opportunities).",
                        evidence={"recommendations": recs, "gap": total},
                    )
                )
            for o in co.opportunities.items:
                left = o["window_close"] - now
                if o["status"] == "open" and 0 < left <= 20 and len(o["accepted"]) < o["headcount"]:
                    out.append(
                        Risk(
                            risk_type="opportunity_window_closing",
                            severity="info",
                            category=EvidenceCategory.OBSERVATION,
                            metric="next_day_readiness",
                            projected_impact=o["headcount"] - len(o["accepted"]),
                            detected_at_minute=now,
                            summary=f"{o['type']} {o['id']} for {o['frame']} closes at "
                            f"{o['window_close_clock']} with {len(o['submitted'])} submitted / "
                            f"{len(o['accepted'])} accepted of {o['headcount']}.",
                            evidence={"id": o["id"], "frame": o["frame"], "type": o["type"]},
                        )
                    )
        if (
            co.plan
            and (co.plan["rotation_compliance"] < 0.9 or co.rotation_stats.get("unfilled", 0) > 0)
            and not co.rotation_stats.get("rerun")
        ):
            out.append(
                Risk(
                    risk_type="rotation_violation",
                    severity="info",
                    category=EvidenceCategory.CALCULATED,
                    metric="next_day_readiness",
                    projected_impact=co.rotation_stats.get("violations", 0)
                    + co.rotation_stats.get("unfilled", 0),
                    detected_at_minute=now,
                    summary="Tomorrow's rotation: compliance "
                    f"{co.plan['rotation_compliance']:.0%}, "
                    f"{co.rotation_stats.get('unfilled', 0)} slot(s) unfilled — re-run rotation "
                    "after the latest opportunities.",
                    evidence=dict(co.rotation_stats),
                )
            )
        last = co.ferry_checks[-1]["clock"] if co.ferry_checks else None
        last_min = int(last[:2]) * 60 + int(last[3:5]) if last and "+" not in last else -1e9
        if now - last_min >= 25 and not co._has("supervisor", "ferry_check"):
            out.append(
                Risk(
                    risk_type="ferry_check_due",
                    severity="info",
                    category=EvidenceCategory.OBSERVATION,
                    metric="next_day_readiness",
                    projected_impact=sum(1 for t in co.trips if t["via_ferry"]),
                    detected_at_minute=now,
                    summary=f"Last ferry check {last or 'never'} — the final truckfile can still "
                    "change; re-checking ferry status.",
                    evidence={"last": last},
                )
            )
    open_g = [g for g in co.gtdr if g["status"] == "open"]
    if open_g:
        out.append(
            Risk(
                risk_type="gtdr_open",
                severity="info",
                category=EvidenceCategory.OBSERVATION,
                metric="next_day_readiness",
                projected_impact=len(open_g),
                detected_at_minute=now,
                summary=f"{len(open_g)} GTDR(s) open: "
                + ", ".join(f"{g['gtdr_id']} {g['trailer']}" for g in open_g[:4]),
                evidence={"ids": [g["gtdr_id"] for g in open_g]},
            )
        )
    return out
