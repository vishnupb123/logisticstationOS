"""Point-in-time snapshot of the Station Operations Twin plus its metric set.

Metric status (docs/OPERATIONAL_DOMAIN_MODEL.md §4.1): every metric here is
`proposed` — a draft definition for a *synthetic* station, never a validated
organisational formula. DEA follows the public description in an MIT thesis
on Delivery Estimate Accuracy ("share of items that receive a delivery
attempt on or before the promised date"); the others are generic operational
definitions written out in METRIC_DEFINITIONS so the UI shows exactly how
each number was computed.
"""

import heapq
from collections import Counter
from typing import Literal

from pydantic import BaseModel

from app.simulation.station_ops.model import StationOpsTwin, clock

_P = "proposed"
METRIC_DEFINITIONS: dict[str, dict] = {
    "dea": {
        "label": "Delivery Estimate Accuracy",
        "status": _P,
        "formula": "today's packages with a delivery attempt on/before promise date / today's "
        "packages promised (incl. rolled-over, left-behind, held, cancelled-inbound)",
    },
    "otd": {
        "label": "On-Time Departure",
        "status": _P,
        "formula": "routes departed <= planned depart + tolerance / routes departed (current plan)",
    },
    "otd_original_plan": {
        "label": "OTD vs. original plan",
        "status": _P,
        "formula": "as OTD, measured against the wave plan before any route moves",
    },
    "sort_compliance": {
        "label": "Sort Compliance",
        "status": _P,
        "formula": "1 - missorted packages / packages sorted",
    },
    "timely_staged": {
        "label": "Timely Staged",
        "status": _P,
        "formula": "routes fully staged at or before stage-by / routes staged",
    },
    "scan_compliance": {
        "label": "Scan Compliance",
        "status": _P,
        "formula": "first-pass clean single reads / induct attempts",
    },
    "stow_wip_compliance": {
        "label": "Est. Stow WIP Compliance",
        "status": _P,
        "formula": "share of 5-min samples in the stow window with stow WIP (queued "
        "packages / total stow rate, in minutes of work) inside the band",
    },
    "induct_fph": {
        "label": "Induct FPH",
        "status": _P,
        "formula": "packages inducted in the trailing 60 minutes (all lines)",
    },
    "stow_pph": {
        "label": "Stow PPH / stower",
        "status": _P,
        "formula": "packages stowed in the trailing 60 min / active stowers",
    },
    "lost_hours": {
        "label": "Induct lost hours",
        "status": _P,
        "formula": "sum of induct-line down time (planned + jams) inside the induct window",
    },
    "induct_downtime_dpmo": {
        "label": "Induct downtime DPMO",
        "status": _P,
        "formula": "packages that could have been inducted during down time / "
        "(inducted + those) x 1,000,000",
    },
    "hv_custody_compliance": {
        "label": "HV custody compliance",
        "status": _P,
        "formula": "high-value packages dispatched with both custody scans / HV "
        "packages dispatched",
    },
    "swipe_compliance": {
        "label": "Swipe-to-finish compliance",
        "status": _P,
        "formula": "returned drivers who swiped to finish / drivers returned",
    },
    "rts_rate": {
        "label": "RTS rate",
        "status": _P,
        "formula": "failed + not-attempted packages returning to station / packages dispatched",
    },
    "units_per_labor_hour": {
        "label": "Units per labor hour",
        "status": _P,
        "formula": "(inducted + stowed + picked) / associate hours on the floor",
    },
}


class Metric(BaseModel):
    key: str
    value: float | None
    target: float | None
    unit: Literal["ratio", "count", "per_hour", "minutes", "hours", "dpmo"]


class Alert(BaseModel):
    severity: Literal["info", "warning", "critical"]
    message: str
    area: str = "station"


class StationOpsSnapshot(BaseModel):
    frame: int
    minute: float
    clock: str
    phase: Literal[
        "pre_shift", "inbound_induct_stow", "pick_stage", "depart", "on_road", "complete"
    ]
    done: bool
    day_complete: bool
    scenario: str
    seed: int
    ofd_date: str
    station_code: str
    cycle: dict
    package_status: dict[str, int]
    inbound: dict
    trips: list[dict]
    induct: dict
    sort: dict
    stow: dict
    outbound: dict
    routes: list[dict]
    delivery: dict
    labor: dict
    metrics: dict[str, Metric]
    series: dict[str, list[float]]
    alerts: list[Alert]
    interventions_applied: list[dict]
    source_kind: Literal["simulated"] = "simulated"


STATUSES = (
    "pending_receive",
    "pending_induct",
    "inducting",
    "problem_solve",
    "hv_pending_scan_in",
    "hv_in_cage",
    "pending_stow",
    "stowing",
    "jackpot",
    "stowed",
    "picked",
    "staged",
    "on_road",
    "rolled_over",
    "left_behind",
    "held_damaged",
    "cancelled_inbound",
)
LABOR_ROLES = ("induct", "stow", "pick", "problem_solve", "high_value")


def _ratio(num: float, den: float) -> float | None:
    return None if den == 0 else num / den


def project_routes(twin: StationOpsTwin) -> dict[int, float]:
    """Projected staged time (seconds) for every route not yet staged: greedy
    assignment of remaining routes (priority, stage-by order) to the pick
    labor that will exist. A projection — reported as such, never as fact."""
    lab, o = twin.config.labor, twin.config.outbound
    now = twin.env.now
    pending = [
        r for r in twin.routes if r.status in ("not_ready", "ready", "picking") and not r.sidelined
    ]
    if not pending:
        return {}

    def est(r) -> float:
        n = sum(
            1
            for i in r.packages
            if twin.pkgs[i].status
            not in ("rolled_over", "left_behind", "cancelled_inbound", "held_damaged")
        )
        bags = max(1, -(-n // o.packages_per_bag))
        carts = max(1, -(-bags // o.bags_per_cart))
        return (
            lab.pick_base_minutes * 60
            + n * lab.pick_seconds_per_package
            + carts * lab.stage_minutes_per_cart * 60
        )

    if not twin.pick_started:
        start = max(now, twin.cutoff)
        pickers = sum(1 for a in twin.assocs if a.present and a.role in ("stow", "induct", "pick"))
        avail = [start] * max(1, pickers)
        picking = []
    else:
        picking = [r for r in pending if r.status == "picking"]
        free = max(0, twin.active("pick") - len(picking))
        avail = [max(now, r.pick_eta or now) for r in picking] + [now] * free
        avail = avail or [now]
    heapq.heapify(avail)
    out = {r.idx: max(now, r.pick_eta or now) + 60 for r in picking}
    for r in sorted((r for r in pending if r.status != "picking"), key=twin.route_key):
        t = heapq.heappop(avail)
        finish = t + est(r)
        out[r.idx] = finish
        heapq.heappush(avail, finish)
    return out


def _route_rows(twin: StationOpsTwin, projected: dict[int, float]) -> list[dict]:
    o = twin.config.outbound
    now = twin.env.now
    rows = []
    for r in twin.routes:
        proj = projected.get(r.idx)
        d = twin.drivers[r.driver] if r.driver is not None else None
        n_pk = len(r.packages)
        bags_total = max(1, -(-n_pk // o.packages_per_bag))
        if r.status == "picking" and r.pick_eta and r.pick_started_at:
            frac = min(1.0, (now - r.pick_started_at) / max(1.0, r.pick_eta - r.pick_started_at))
            bags_done = int(frac * bags_total)
        elif r.picked_at is not None:
            bags_done = r.bags or bags_total
        else:
            bags_done = 0
        late = (
            max(0.0, (r.departed_at - r.planned_depart) / 60) if r.departed_at is not None else None
        )
        rows.append(
            {
                "route_id": r.route_id,
                "dsp": r.dsp,
                "cluster": r.cluster,
                "aisle": r.aisle,
                "staging_location": r.staging_location,
                "wave": r.wave + 1,
                "stage_by": clock(r.stage_by / 60),
                "planned_depart": clock(r.planned_depart / 60),
                "original_depart": clock(r.original_depart / 60),
                "moved_waves": r.moved_waves,
                "status": r.status,
                "priority": r.priority,
                "sidelined": r.sidelined,
                "picker": r.picker,
                "spr": n_pk,
                "spr_flag": "high" if n_pk > o.spr_high else "low" if n_pk < o.spr_low else None,
                "bags_done": bags_done,
                "bags_total": r.bags or bags_total,
                "carts": r.carts,
                "carts_staged": r.carts_staged,
                "hv_pending": r.hv_pending,
                "pick_minutes": round((r.picked_at - r.pick_started_at) / 60, 1)
                if r.picked_at and r.pick_started_at
                else None,
                "picked": r.picked_count,
                "staged_at": clock(r.staged_at / 60) if r.staged_at is not None else None,
                "departed_at": clock(r.departed_at / 60) if r.departed_at is not None else None,
                "depart_late_minutes": late,
                "projected_stage_at": clock(proj / 60) if proj is not None else None,
                "at_risk": proj is not None and proj > r.stage_by,
                "not_attempted": r.not_attempted,
                "failed": r.failed,
                "driver": d.driver_id if d else None,
                "driver_state": d.state if d else None,
                "driver_late_by": round(twin.driver_late_by(d), 1)
                if d and d.state in ("off_duty", "en_route")
                else None,
            }
        )
    return rows


def build_snapshot(twin: StationOpsTwin, frame: int) -> StationOpsSnapshot:  # noqa: C901
    c = twin.config
    now = twin.env.now
    now_min = now / 60
    today = [p for p in twin.pkgs if not p.carryover]
    statuses = Counter(p.status for p in twin.pkgs)
    status_counts = {k: statuses.get(k, 0) for k in STATUSES}

    trips = []
    for i, plan in enumerate(c.linehauls):
        known = plan.known_delay(now_min)
        eta = plan.planned_arrival_minute + known
        tr = twin.trips[i]
        trips.append(
            {
                "trip_id": plan.trip_id,
                "origin": plan.origin,
                "via_ferry": plan.via_ferry,
                "ferry_sailing": plan.ferry_sailing,
                "planned_arrival": clock(plan.planned_arrival_minute),
                "planned_minute": plan.planned_arrival_minute,
                "eta": clock(eta),
                "eta_minute": eta,
                "delay_minutes": known,
                "revision_count": sum(1 for r in plan.revisions if r.reveal_minute <= now_min),
                "delay_reason": plan.delay_reason if known else None,
                "status": tr.status,
                "door": tr.door,
                "volume": plan.volume,
                "actual_arrival": clock(tr.yard_at / 60) if tr.yard_at else None,
                "unload_sequence": tr.sequence,
                "priority": tr.priority,
                "arrives_after_pick_start": (not plan.cancelled)
                and tr.yard_at is None
                and eta * 60 >= twin.cutoff,
            }
        )

    k = twin.counters
    window_end = min(twin.cutoff, now)
    lost_s = 0.0
    for _ln, s, e, _why in twin.line_down_windows:
        lost_s += max(0.0, min(e, window_end) - max(s, c.induct.start_minute * 60))
    lost_pkgs = lost_s / 3600 * c.induct.rate_pph_per_line
    defects = k["no_read"] + k["multi_read"] + k["misapplied_label"]
    stowers = twin.active("stow")
    stowed_hour = twin.rate_last_hour(twin._stowed_times)
    induct_fph = twin.rate_last_hour(twin._inducted_times)

    tol = c.dispatch.otd_tolerance_minutes * 60
    projected = project_routes(twin)
    routes = _route_rows(twin, projected)
    staged = sum(1 for r in twin.routes if r.staged_at is not None)
    timely = sum(1 for r in twin.routes if r.staged_at is not None and r.staged_at <= r.stage_by)
    dep = [r for r in twin.routes if r.departed_at is not None]
    on_time = sum(1 for r in dep if r.departed_at <= r.planned_depart + tol)
    on_time_orig = sum(1 for r in dep if r.departed_at <= r.original_depart + tol)
    at_risk = sum(1 for r in routes if r["at_risk"])
    route_status = Counter(r.status for r in twin.routes)

    promised = len(today)
    attempted = sum(1 for p in today if p.attempted)
    not_attempted = sum(1 for p in today if p.attempted is False)
    misses = sum(
        1
        for p in today
        if p.status in ("rolled_over", "left_behind", "cancelled_inbound", "held_damaged")
    )
    known_misses = misses + not_attempted
    if twin.done:
        known_misses += sum(1 for p in today if p.status == "pending_receive")
    delivered_now = sum(1 for p in today if p.attempt_at and p.attempt_at <= now and p.delivered)
    failed_now = sum(
        1 for p in today if p.attempt_at and p.attempt_at <= now and p.delivered is False
    )
    dispatched = sum(1 for p in twin.pkgs if p.departed_at is not None)
    hv_disp = [p for p in twin.pkgs if p.hv and p.departed_at is not None]
    returned = [d for d in twin.drivers if d.return_at and d.return_at <= now]
    swiped = sum(1 for d in returned if d.swiped_at is not None and d.swiped_at <= now)
    labor_hours = sum(sum(twin.series.get(f"labor_{r}", [])) for r in LABOR_ROLES)

    t = c.targets
    metrics = {
        "dea": Metric(
            key="dea",
            value=_ratio(attempted, promised) if twin.done else None,
            target=t.dea,
            unit="ratio",
        ),
        "dea_ceiling": Metric(
            key="dea_ceiling",
            value=_ratio(promised - known_misses, promised),
            target=t.dea,
            unit="ratio",
        ),
        "otd": Metric(key="otd", value=_ratio(on_time, len(dep)), target=t.otd, unit="ratio"),
        "otd_original_plan": Metric(
            key="otd_original_plan",
            value=_ratio(on_time_orig, len(dep)),
            target=t.otd,
            unit="ratio",
        ),
        "sort_compliance": Metric(
            key="sort_compliance",
            value=None if k["sorted"] == 0 else 1 - k["missorts"] / k["sorted"],
            target=t.sort_compliance,
            unit="ratio",
        ),
        "timely_staged": Metric(
            key="timely_staged", value=_ratio(timely, staged), target=t.timely_staged, unit="ratio"
        ),
        "scan_compliance": Metric(
            key="scan_compliance",
            value=_ratio(k["induct_attempts"] - defects - k["damaged"], k["induct_attempts"]),
            target=t.scan_compliance,
            unit="ratio",
        ),
        "stow_wip_compliance": Metric(
            key="stow_wip_compliance",
            value=_ratio(sum(twin._wip_samples), len(twin._wip_samples)),
            target=c.stow.wip_compliance_target,
            unit="ratio",
        ),
        "induct_fph": Metric(
            key="induct_fph",
            value=induct_fph,
            target=twin.total_lines() * c.induct.rate_pph_per_line,
            unit="per_hour",
        ),
        "stow_pph": Metric(
            key="stow_pph",
            value=stowed_hour / stowers if stowers else None,
            target=c.stow.rate_pph_per_stower,
            unit="per_hour",
        ),
        "lost_hours": Metric(
            key="lost_hours", value=round(lost_s / 3600, 2), target=0, unit="hours"
        ),
        "induct_downtime_dpmo": Metric(
            key="induct_downtime_dpmo",
            value=round(lost_pkgs / max(1.0, k["inducted"] + lost_pkgs) * 1e6),
            target=None,
            unit="dpmo",
        ),
        "hv_custody_compliance": Metric(
            key="hv_custody_compliance",
            value=_ratio(sum(1 for p in hv_disp if p.custody_scans >= 2), len(hv_disp)),
            target=t.hv_custody,
            unit="ratio",
        ),
        "swipe_compliance": Metric(
            key="swipe_compliance",
            value=_ratio(swiped, len(returned)),
            target=t.swipe_compliance,
            unit="ratio",
        ),
        "rts_rate": Metric(
            key="rts_rate",
            value=_ratio(failed_now + not_attempted, dispatched),
            target=None,
            unit="ratio",
        ),
        "units_per_labor_hour": Metric(
            key="units_per_labor_hour",
            value=_ratio(k["inducted"] + k["stowed"] + k["picked"], labor_hours),
            target=None,
            unit="per_hour",
        ),
    }

    if twin.day_complete:
        phase = "complete"
    elif twin.done:
        phase = "on_road"
    elif now_min < c.induct.start_minute:
        phase = "pre_shift"
    elif not twin.pick_started:
        phase = "inbound_induct_stow"
    elif any(route_status.get(s, 0) for s in ("ready", "picking", "staging")):
        phase = "pick_stage"
    else:
        phase = "depart"

    alerts: list[Alert] = []
    if twin.pick_started:
        alerts.append(
            Alert(
                severity="warning",
                area="cycle",
                message=(
                    f"Pick has started for {c.cycle.name} — induct into this cycle is blocked; "
                    f"{status_counts['rolled_over']} package(s) rolled over."
                ),
            )
        )
    for ln in range(1, twin.total_lines() + 1):
        why = twin.line_down(ln)
        if why:
            alerts.append(
                Alert(
                    severity="critical",
                    area="induct",
                    message=f"Induct line L{ln} is down ({why}).",
                )
            )
    for tv in trips:
        if tv["status"] == "in_transit" and tv["delay_minutes"] >= 30:
            ferry = f", ferry {tv['ferry_sailing']}" if tv["via_ferry"] else ""
            after = " (after pick start)" if tv["arrives_after_pick_start"] else ""
            alerts.append(
                Alert(
                    severity="critical" if tv["arrives_after_pick_start"] else "warning",
                    area="inbound",
                    message=f"{tv['trip_id']} ({tv['origin']}{ferry}) delayed "
                    f"{tv['delay_minutes']:.0f} min — ETA {tv['eta']}{after}",
                )
            )
    if at_risk:
        alerts.append(
            Alert(
                severity="warning",
                area="outbound",
                message=f"{at_risk} route(s) projected to miss stage-by.",
            )
        )
    late_drivers = [r for r in routes if (r["driver_late_by"] or 0) > 0]
    if late_drivers:
        alerts.append(
            Alert(
                severity="warning",
                area="dispatch",
                message=f"{len(late_drivers)} driver(s) projected late for check-in.",
            )
        )
    if len(twin.hv_q) > 25:
        alerts.append(
            Alert(
                severity="warning",
                area="high_value",
                message=f"{len(twin.hv_q)} high-value tasks queued at the cage.",
            )
        )

    present = [a for a in twin.assocs if a.present]
    return StationOpsSnapshot(
        frame=frame,
        minute=now_min,
        clock=clock(now_min),
        phase=phase,
        done=twin.done,
        day_complete=twin.day_complete,
        scenario=c.name,
        seed=c.seed,
        ofd_date=c.ofd_date.isoformat(),
        station_code=c.station_code,
        cycle={
            "name": c.cycle.name,
            "induct_start": clock(c.induct.start_minute),
            "pick_start": clock(twin.cutoff / 60),
            "pick_start_minute": twin.cutoff / 60,
            "planned_pick_start": clock(c.cycle.pick_start_minute),
            "induct_blocked": twin.pick_started,
            "cutoff_extension_minutes": twin.cutoff_extension_minutes,
        },
        package_status=status_counts,
        inbound={
            "trips_planned": len(trips),
            "trips_arrived": sum(1 for x in trips if x["status"] in ("arrived", "unloading")),
            "trips_in_yard": sum(1 for x in trips if x["status"] == "in_yard"),
            "trips_late": sum(1 for x in trips if x["delay_minutes"] >= 15),
            "trips_cancelled": sum(1 for x in trips if x["status"] == "cancelled"),
            "planned_volume": c.planned_volume,
            "arrived_volume": k["arrived"],
            "unmanifested_arrived": k["unmanifested_arrived"],
            "late_volume_after_pick_start": sum(
                x["volume"] for x in trips if x["arrives_after_pick_start"]
            ),
            "doors": c.doors,
            "doors_free": twin.doors_free,
        },
        trips=trips,
        induct={
            "lines": twin.total_lines(),
            "active_lines": twin.active("induct"),
            "down_lines": [ln for ln in range(1, twin.total_lines() + 1) if twin.line_down(ln)],
            "attempts": k["induct_attempts"],
            "inducted": k["inducted"],
            "no_reads": k["no_read"],
            "multi_reads": k["multi_read"],
            "misapplied_labels": k["misapplied_label"],
            "damaged": k["damaged"],
            "no_read_rate": _ratio(k["no_read"], k["induct_attempts"]),
            "multi_read_rate": _ratio(k["multi_read"], k["induct_attempts"]),
            "fph_last_hour": induct_fph,
            "queue": len(twin.induct_q),
            "problem_queue": len(twin.problem_q),
        },
        sort={"sorted": k["sorted"], "missorts": k["missorts"], "jackpot": k["jackpot"]},
        stow={
            "stowers": stowers,
            "planned_stowers": c.stow.stowers,
            "stowed": k["stowed"],
            "wip_packages": len(twin.stow_q),
            "wip_minutes": round(twin.wip_minutes(), 1),
            "wip_target_min": c.stow.wip_target_min,
            "wip_target_max": c.stow.wip_target_max,
        },
        outbound={
            "routes_total": len(twin.routes),
            **{
                s: route_status.get(s, 0)
                for s in (
                    "not_ready",
                    "ready",
                    "picking",
                    "staging",
                    "staged",
                    "loading",
                    "departed",
                )
            },
            "at_risk": at_risk,
            "sidelined": sum(1 for r in twin.routes if r.sidelined),
            "pickers": twin.active("pick"),
            "drivers_late": len(late_drivers),
        },
        routes=routes,
        delivery={
            "promised": promised,
            "attempted": attempted,
            "not_attempted": not_attempted,
            "known_misses": known_misses,
            "delivered_so_far": delivered_now,
            "failed_so_far": failed_now,
            "dispatched": dispatched,
        },
        labor={
            "present": len(present),
            "planned": sum(1 for a in twin.assocs if not a.vet),
            "absent": sum(1 for a in twin.assocs if not a.present),
            "flex_remaining": twin.flex_remaining,
            "by_role": dict(Counter(a.role for a in present if a.task != "off_shift")),
        },
        metrics=metrics,
        series={key: list(v) for key, v in twin.series.items()},
        alerts=alerts,
        interventions_applied=list(twin.applied),
    )


def run_station_day(config, interventions=None) -> StationOpsSnapshot:
    twin = StationOpsTwin(config, interventions)
    twin.run_to_end()
    return build_snapshot(twin, frame=0)
