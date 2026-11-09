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


AgentName = Literal["inbound", "sort_stow", "outbound", "dispatch", "quality"]

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
}

AGENT_LABEL: dict[str, str] = {
    "inbound": "Inbound Agent",
    "sort_stow": "Sort & Stow Agent",
    "outbound": "Outbound Agent",
    "dispatch": "Dispatch Agent",
    "quality": "Quality & HV Agent",
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
    nominal = lines * c.rate_pph_per_line
    return max(0.5, min(1.0, observed / nominal)) if observed else 1.0


def induct_capacity(twin: StationOpsTwin, start: float, end: float) -> float:
    """Packages the staffed induct lines can process in [start, end] minutes,
    net of *known* down time (planned outages + jams already under way),
    scaled by the throughput actually observed (`observed_induct_factor`)."""
    per_line = twin.config.induct.rate_pph_per_line / 60 * observed_induct_factor(twin)
    total = 0.0
    for line in _staffed_lines(twin):
        minutes = max(0.0, end - start)
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
        induct_rate = n_lines * c.induct.rate_pph_per_line / 60 * observed_induct_factor(twin)

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

        stow_work = ps["pending_stow"] + ps["stowing"] + min(induct_work, int(cap))
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
                projected_impact=int(c.induct.rate_pph_per_line * len(down)),
                summary=f"Induct line(s) {', '.join(f'L{x}' for x in down)} down "
                f"(lost hours so far {snap.metrics['lost_hours'].value}h).",
                evidence={"lines": down},
            )

        wip = snap.stow["wip_minutes"]
        lo, hi = c.stow.wip_target_min, c.stow.wip_target_max
        if now >= c.induct.start_minute + 30 and snap.stow["stowers"]:
            if wip > hi * 1.3:
                add(
                    risk_type="stow_wip_above_band",
                    severity="warning",
                    category=EvidenceCategory.OBSERVATION,
                    metric="dea",
                    projected_impact=snap.stow["wip_packages"],
                    summary=f"Stow WIP {wip:.0f} min of work is above the {lo:.0f}–{hi:.0f} min "
                    "band — stow is the bottleneck.",
                    evidence={"wip_minutes": wip, "band": [lo, hi]},
                )
            elif wip < lo * 0.5 and snap.induct["queue"] < 50 and now < cutoff - 60:
                add(
                    risk_type="stow_wip_below_band",
                    severity="info",
                    category=EvidenceCategory.OBSERVATION,
                    metric="labor",
                    projected_impact=snap.stow["stowers"],
                    summary=f"Stow WIP {wip:.1f} min is below the {lo:.0f}–{hi:.0f} min band — "
                    "stowers are starved; labor could help problem solve or the HV cage.",
                    evidence={"wip_minutes": wip, "band": [lo, hi]},
                )

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
    return risks
