"""v2 page views (HANDOFF_V2 §4/§8): receive with containers and trip legs,
induct status ladders, fingers, stow breakdown per cluster, plan vs. actual,
associate performance by path, shift plan / opportunities / rotation,
cycles, unified work items, settings and the metric spec sheet.

All read-only functions of the twin; synthetic throughout.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from app.simulation.station_ops import labor_plan as lp
from app.simulation.station_ops import status as st
from app.simulation.station_ops.metrics import SPECS
from app.simulation.station_ops.model import StationOpsTwin, _u, clock
from app.simulation.station_ops.plan import PITCH_CHAPTERS

SIZES = ("Small", "Medium", "Large")


def _size(p) -> str:
    u = _u("size", p.tracking_id)
    return "Small" if u < 0.55 else "Medium" if u < 0.88 else "Large"


# --- receive -----------------------------------------------------------------------


def _ladder(pkgs, planned: bool | None) -> dict:
    sel = [p for p in pkgs if planned is None or p.planned == planned]
    c = Counter(p.status for p in sel)
    inducted = sum(1 for p in sel if p.inducted_at is not None)
    return {
        "manifested": sum(1 for p in sel if p.status == "pending_receive"),
        "in_transit": 0,
        "arrived": sum(1 for p in sel if p.arrived_at is not None),
        "marked_for_reprocess": sum(
            1
            for p in sel
            if p.ps_state in ("pending_reinduct", "pending_stow") or p.status == "problem_solve"
        ),
        "inducted": inducted,
        "stow_buffered": c["stow_buffered"],
        "stowed": sum(1 for p in sel if p.stowed_at is not None),
        "sidelined": c["held_damaged"] + c["pending_approval"],
    }


def receive_v2(tw: StationOpsTwin, snap: dict) -> dict:
    now_min = tw.now_minute
    cfg = tw.config
    cycles = {}
    for cyc, pred in (("CYCLE_1", lambda p: not p.hv), ("High_Value", lambda p: p.hv)):
        pk = [p for p in tw.pkgs if pred(p)]
        planned = [p for p in pk if p.planned and p.trip >= 0]
        promised = snap["delivery"]["promised"]
        ceiling = snap["metrics"]["dea_ceiling"]["value"] or 0
        cycles[cyc] = {
            "predicted_dispatch": round(len(pk) * ceiling) if promised else 0,
            "current_cycle_planned": len(planned),
            "current_cycle_arrived": sum(1 for p in planned if p.arrived_at is not None),
            "other_unplanned_arrived": sum(
                1 for p in pk if not p.planned and p.arrived_at is not None
            ),
            "total_arrived": sum(1 for p in pk if p.arrived_at is not None),
            "planned": _ladder(pk, True),
            "unplanned": _ladder(pk, False),
        }
    trips = []
    for i, plan in enumerate(cfg.linehauls):
        t = tw.trips[i]
        ids = tw.trip_pkgs[i]
        pk = [tw.pkgs[x] for x in ids]
        known = plan.known_delay(now_min)
        eta = plan.planned_arrival_minute + known
        arrived_state = t.status in ("unloading", "arrived")
        status = (
            "Cancelled"
            if t.status == "cancelled"
            else "In Yard"
            if t.status in ("in_yard",) or (t.yard_at is not None and t.status == "unloading")
            else "Arrived"
            if arrived_state
            else "Pending Depart"
            if now_min < (plan.legs[0]["planned_depart"] if plan.legs else eta - 120)
            else "In-Transit"
        )
        legs = []
        for leg in plan.legs:
            arr = leg["planned_arrive"] + (
                known if leg is plan.legs[-1] or leg["mode"] == "ferry" else 0
            )
            legs.append(
                {
                    **leg,
                    "planned_depart_clock": clock(leg["planned_depart"]),
                    "planned_arrive_clock": clock(leg["planned_arrive"]),
                    "eta_clock": clock(arr),
                    "state": "done"
                    if now_min >= arr or arrived_state
                    else "active"
                    if now_min >= leg["planned_depart"]
                    else "planned",
                }
            )
        issues = []
        if known >= 15:
            issues.append(
                {
                    "kind": "late",
                    "text": f"{'Ferry leg' if plan.via_ferry else 'Road leg'} delayed {known:.0f} min"
                    + (f" — {plan.delay_reason}" if plan.delay_reason else ""),
                }
            )
        if plan.cancelled:
            issues.append({"kind": "cancelled", "text": "Trip cancelled"})
        if (
            t.yard_at is not None
            and t.arrived_at is None
            and tw.env.now - max(t.yard_at, 0) > 60 * 60
        ):
            issues.append({"kind": "dwell", "text": "Waiting in yard over 60 min"})
        clusters = Counter(tw.routes[p.route].cluster for p in pk)
        sizes = Counter(_size(p) for p in pk)
        cyc = Counter(st.cycle_column(p) for p in pk)
        containers = []
        for cid in tw.trip_containers[i]:
            cont = tw.containers[cid]
            pend = sum(
                1
                for x in cont["pkgs"]
                if tw.pkgs[x].status in ("pending_receive", "pending_induct")
            )
            containers.append(
                {
                    "id": cont["id"],
                    "type": cont["type"],
                    "pending_induct": pend,
                    "total": len(cont["pkgs"]),
                }
            )
        trips.append(
            {
                "trip_id": plan.trip_id,
                "origin": plan.origin,
                "status": status,
                "location": f"Door {t.door}"
                if t.door
                else ("Yard" if t.status == "in_yard" else None),
                "planned": clock(plan.planned_arrival_minute),
                "planned_minute": plan.planned_arrival_minute,
                "eta": clock(eta),
                "actual": clock(t.yard_at / 60) if t.yard_at is not None else None,
                "volume": plan.volume
                if (t.yard_at is not None or now_min >= plan.planned_arrival_minute - 240)
                else None,
                "unload_sequence": t.sequence,
                "via_ferry": plan.via_ferry,
                "operator_type": plan.operator_type,
                "tractor": plan.tractor,
                "trailer": plan.trailer,
                "legs": legs,
                "issues": issues,
                "watched": plan.trip_id in tw.watch,
                "group": {
                    "package_size": dict(sizes),
                    "destination": {"Station": len(pk)},
                    "station_ead": {tw.config.ofd_date.isoformat(): len(pk)},
                    "cycle": dict(cyc),
                    "cluster": dict(clusters),
                },
                "containers": containers,
                "unplanned_share": plan.unplanned_share,
            }
        )
    trips.sort(key=lambda x: (x["status"] not in ("In Yard", "Arrived"), x["planned_minute"]))
    return {
        "cycles": cycles,
        "linehauls": trips,
        "watch": sorted(tw.watch),
        "group_by": ["none", "package_size", "destination", "station_ead", "cycle", "cluster"],
    }


# --- induct ---------------------------------------------------------------------------


def induct_v2(tw: StationOpsTwin) -> dict:
    cols = {
        "CYCLE_1": [p for p in tw.pkgs if not p.hv and p.planned],
        "High_Value": [p for p in tw.pkgs if p.hv],
        "Unplanned": [p for p in tw.pkgs if not p.planned],
    }
    overall = {}
    for k, pk in cols.items():
        c = Counter(p.status for p in pk)
        overall[k] = {
            "current_cycle_planned": sum(1 for p in pk if p.planned),
            "current_cycle_inducted": sum(1 for p in pk if p.inducted_at is not None and p.planned),
            "other_unplanned_inducted": sum(
                1 for p in pk if p.inducted_at is not None and not p.planned
            ),
            "total_inducted": sum(1 for p in pk if p.inducted_at is not None),
            "manifested": c["pending_receive"],
            "arrived": sum(1 for p in pk if p.arrived_at is not None),
            "marked_for_reprocess": sum(1 for p in pk if p.ps_state in ("pending_reinduct",)),
            "inducted": c["pending_stow"] + c["stowing"],
            "stow_buffered": c["stow_buffered"],
            "stowed": sum(1 for p in pk if p.stowed_at is not None),
            "sidelined": c["held_damaged"] + c["pending_approval"] + c["missed_induct"],
        }
    areas = []
    now = tw.env.now
    for ln in range(1, tw.total_lines() + 1):
        ls = tw.line_stats[ln]
        recent = [t for t in tw._line_scan_times.get(ln, []) if t >= now - 3600]
        who = next(
            (a for a in tw.assocs if a.present and a.role == "induct" and a.line == ln), None
        )
        areas.append(
            {
                "line": tw.line_name(ln),
                "type": "Automated" if tw.is_automated(ln) else "Manual",
                "status": "Down" if tw.line_down(ln) else "Running" if who else "Unstaffed",
                "down_reason": tw.line_down(ln),
                "inductor": who.login if who else None,
                "target_pph": tw.line_rate(ln),
                "pph_last_hour": len(recent),
                "inducted": ls["inducted"],
                "lost_hours": round(tw.gap_lost_s[ln] / 3600, 2),
                "stops": tw.gap_stops[ln],
                "no_read": ls["no_read"],
                "multi_read": ls["multi_read"],
                "misapplied_label": ls["misapplied_label"],
            }
        )
    containers = []
    for i, plan in enumerate(tw.config.linehauls):
        rows = []
        for cid in tw.trip_containers[i]:
            cont = tw.containers[cid]
            pend = sum(
                1
                for x in cont["pkgs"]
                if tw.pkgs[x].status in ("pending_receive", "pending_induct", "inducting")
            )
            clusters = Counter(tw.routes[tw.pkgs[x].route].cluster for x in cont["pkgs"])
            rows.append(
                {
                    "id": cont["id"],
                    "type": cont["type"],
                    "pending_induct": pend,
                    "total": len(cont["pkgs"]),
                    "unloaded": cont["unloaded_at"] is not None,
                    "clusters": dict(clusters),
                }
            )
        if any(r["pending_induct"] for r in rows) or tw.trips[i].arrived_at is not None:
            containers.append({"linehaul": plan.trip_id, "containers": rows})
    return {
        "overall": overall,
        "areas": areas,
        "containers": containers,
        "noncon_queue": len(tw.noncon_q),
        "noncon_total": tw.counters["noncon"],
    }


# --- stow breakdown / fingers -------------------------------------------------------


def stow_v2(tw: StationOpsTwin) -> dict:
    now = tw.env.now
    rows = []
    o = tw.config.outbound
    for cl in tw.config.sort.clusters:
        pk = [p for p in tw.pkgs if not p.hv and tw.routes[p.route].cluster == cl]
        c = Counter(p.status for p in pk)
        stowed = sum(1 for p in pk if p.stowed_at is not None)
        last_hour = sum(1 for p in pk if p.stowed_at is not None and p.stowed_at >= now - 3600)
        active = sum(
            1 for a in tw.assocs if a.task == "stowing" and a.location.startswith(f"Aisle {cl}")
        )
        pending = c["pending_stow"] + c["stowing"]
        caught = sum(
            1
            for p in pk
            if p.misdivert_kind and p.ps_state in ("misdivert", "pending_reinduct", "resolved")
        )
        rows.append(
            {
                "cluster": cl,
                "planned": len(pk),
                "arrived": sum(1 for p in pk if p.arrived_at is not None),
                "inducted": sum(1 for p in pk if p.inducted_at is not None),
                "stow_buffered": c["stow_buffered"],
                "stowed": stowed,
                "stow_plan": round(stowed / len(pk), 3) if pk else None,
                "ps": c["problem_solve"],
                "jackpot_buffered": c["jackpot"],
                "unopened_bags": math.ceil(c["stow_buffered"] / max(1, o.packages_per_bag)),
                "minutes_of_work": round((pending + c["stow_buffered"]) / max(1, last_hour) * 60, 1)
                if last_hour
                else None,
                "stow_rate": last_hour,
                "scan_compliance": round(1 - caught / max(1, stowed), 4),
                "active_stowers": active,
            }
        )
    fingers = []
    total = max(1, tw.counters["inducted"])
    auto_down = all(tw.line_down(ln) for ln in range(1, tw.config.induct.automated_lines + 1))
    hours = max(1 / 60, (min(now, tw.cutoff) / 60 - tw.config.induct.start_minute) / 60)
    for cl in tw.config.sort.clusters:
        name = f"FINGER-{cl}"
        fs = tw.finger_stats[name]
        fingers.append(
            {
                "machine": name,
                "status": "Down" if auto_down else "Active",
                "clusters": [cl] + [k for k, v in tw.finger_rebalanced.items() if v == name],
                "rebalanced_to": tw.finger_rebalanced.get(cl),
                "buffer": fs["buffer"],
                "bay_capacity": tw.config.sort.finger_bay_capacity,
                "full_bay": fs["buffer"] >= tw.config.sort.finger_bay_capacity,
                "full_bay_events": fs["full_bay"],
                "jackpot_rate": round(fs["jackpot"] / fs["volume"], 4) if fs["volume"] else None,
                "no_read_rate": round(fs["no_read"] / (fs["volume"] + fs["no_read"]), 4)
                if fs["volume"]
                else None,
                "current_volume": fs["buffer"],
                "volume": fs["volume"],
                "pct_station_volume": round(fs["volume"] / total, 3),
                "avg_pph": round(fs["volume"] / hours) if fs["volume"] else 0,
            }
        )
    return {"clusters": rows, "fingers": fingers}


# --- plan vs actual --------------------------------------------------------------------


def plan_vs_actual(tw: StationOpsTwin) -> dict:
    cfg = tw.config
    plan = lp.build_plan(cfg, cfg.planned_volume, pick_start=tw.cutoff / 60)
    fl = lp.flows(cfg, cfg.planned_volume, pick_start=tw.cutoff / 60)
    hours = fl["hours"]
    s = tw.series
    minutes = s.get("minute", [])
    buckets = []
    for k, m in enumerate(minutes):
        buckets.append(
            {
                "minute": m,
                **{
                    key: (s.get(key) or [0] * len(minutes))[k] if k < len(s.get(key) or []) else 0
                    for key in (
                        "arrived",
                        "inducted",
                        "stowed",
                        "picked",
                        "inducted_auto",
                        "inducted_manual",
                        "labor_induct",
                        "labor_stow",
                        "labor_pick",
                        "labor_problem_solve",
                        "labor_high_value",
                        "labor_yard_marshal",
                        "labor_idle",
                        "stowers_active",
                    )
                },
            }
        )
    rows = []
    for i, h in enumerate(hours):
        for q in range(4):
            start = h + q * 15
            b = next((x for x in buckets if x["minute"] == start + 15), None)

            def _p(key, _i=i):
                return round(fl[key][_i] / 4, 1)

            rows.append(
                {
                    "start": start,
                    "label": f"{clock(start)}–{clock(start + 15)}",
                    "receive_planned": _p("receive"),
                    "receive_actual": b["arrived"] if b else None,
                    "induct_planned": _p("induct"),
                    "induct_actual": b["inducted"] if b else None,
                    "induct_auto_planned": _p("auto_induct"),
                    "induct_auto_actual": b["inducted_auto"] if b else None,
                    "induct_manual_planned": _p("manual_induct"),
                    "induct_manual_actual": b["inducted_manual"] if b else None,
                    "stow_planned": _p("stow"),
                    "stow_actual": b["stowed"] if b else None,
                    "pick_planned": _p("pick"),
                    "pick_actual": b["picked"] if b else None,
                    "labor": {
                        "Sort": round(
                            (b["labor_induct"] + b["labor_stow"] + b["labor_problem_solve"]), 1
                        )
                        if b
                        else None,
                        "Pick Stage": round(b["labor_pick"], 1) if b else None,
                        "UTR": round(b["labor_yard_marshal"], 1) if b else None,
                        "Site Support": round(b["labor_high_value"], 1) if b else None,
                        "OTR": 0 if b else None,
                        "RTS": 0 if b else None,
                        "Non-Core Support": 0 if b else None,
                        "Off Task": round(b["labor_idle"], 1) if b else None,
                    },
                    "stowers": b["stowers_active"] if b else None,
                }
            )
    target_induct_pph = sum(tw.line_rate(ln) for ln in range(1, cfg.induct.lines + 1))
    return {
        "intervals": rows,
        "target_induct_pph": target_induct_pph,
        "target_stow_pph": cfg.stow.rate_pph_per_stower,
        "labor_groups": [
            "Sort",
            "Pick Stage",
            "UTR",
            "Site Support",
            "OTR",
            "RTS",
            "Non-Core Support",
            "Off Task",
        ],
        "plan_totals": plan["totals"],
        "note": "Planned = today's synthetic linehaul plan through the documented belt-run-time "
        "rule; OTR/RTS/Non-core are not simulated individually (0).",
    }


# --- associates by path ------------------------------------------------------------------


def _hours_in(a, role: str, now_min: float) -> float:
    h = 0.0
    hist = list(a.history)
    for k, (m, r) in enumerate(hist):
        end = hist[k + 1][0] if k + 1 < len(hist) else now_min
        if r == role:
            h += max(0.0, end - m)
    return h / 60


def associate_performance(tw: StationOpsTwin) -> dict:
    now_min = tw.now_minute
    by_ind = Counter(p.inducted_by for p in tw.pkgs if p.inducted_by)
    by_stow = Counter(p.stowed_by for p in tw.pkgs if p.stowed_by)
    induct, stow, pick = [], [], []
    for a in tw.assocs:
        if not a.present:
            continue
        hi = _hours_in(a, "induct", now_min)
        if hi > 0 or by_ind[a.login]:
            induct.append(
                {
                    "associate": a.login,
                    "pph": round(by_ind[a.login] / hi) if hi > 0.05 else None,
                    "hours": round(hi, 2),
                    "total_packages": by_ind[a.login],
                    "active": a.role == "induct" and a.task not in ("off_shift", "idle"),
                    "location": a.location,
                }
            )
        hs = _hours_in(a, "stow", now_min)
        if hs > 0 or by_stow[a.login]:
            stow.append(
                {
                    "associate": a.login,
                    "pph": round(by_stow[a.login] / hs) if hs > 0.05 else None,
                    "hours": round(hs, 2),
                    "total_packages": by_stow[a.login],
                    "fsaf": a.fsaf,
                    "fsaf_dpmo": round(a.fsaf / by_stow[a.login] * 1e6)
                    if by_stow[a.login]
                    else None,
                    "stow_scan_to_ps": a.stow_to_ps,
                    "spot_checks": a.spot_checks,
                    "spot_check_dpmo": round(a.spot_defects / a.spot_checks * 1e6)
                    if a.spot_checks
                    else None,
                    "active": a.role == "stow" and a.task == "stowing",
                    "last_location": a.location,
                    "cluster": a.location.replace("Aisle ", "")[:1]
                    if a.location.startswith("Aisle")
                    else None,
                }
            )
        hp = _hours_in(a, "pick", now_min)
        if hp > 0:
            on = a.task in ("picking", "staging")
            pick.append(
                {
                    "associate": a.login,
                    "picklist_assigned": on,
                    "time_since_last_activity_min": round((tw.env.now - a.last_activity) / 60, 1)
                    if a.last_activity
                    else None,
                    "picklist_id": a.task_ref if on else None,
                    "current_picklist_minutes": round((tw.env.now - a.task_started) / 60, 1)
                    if on and a.task_started
                    else None,
                    "idle_between_picklists_min": round(a.idle_s / 60, 1),
                    "last_location": a.location,
                    "hours": round(hp, 2),
                    "units": a.units,
                }
            )
    return {
        "induct": sorted(induct, key=lambda r: r["associate"]),
        "stow": sorted(stow, key=lambda r: r["associate"]),
        "pick": sorted(pick, key=lambda r: r["associate"]),
        "pick_summary": {
            "total": len(pick),
            "with_picklist": sum(1 for r in pick if r["picklist_assigned"]),
            "without_picklist": sum(1 for r in pick if not r["picklist_assigned"]),
        },
        "governance": "Individual performance is coaching support only — aggregates by default, "
        "per-associate rows for the manager role (claimed, not authenticated). Never used for "
        "automated ranking or discipline.",
    }


# --- shift plan / opportunities / rotation -------------------------------------------------


def shift_plan_v2(tw: StationOpsTwin) -> dict:
    co = tw.closeout
    cfg = tw.config
    att = cfg.labor.attendance_rate
    sched_today = sum(1 for a in tw.assocs if not a.vet)
    pre_shift = lp.build_plan(
        cfg,
        cfg.planned_volume,
        scheduled={"Single Cycle": sched_today},
        attendance={"Single Cycle": att},
        planned_rollover=len(tw._carryover_ids),
        pick_start=tw.cutoff / 60,
    )
    next_day = (
        co.plan.get("labor_plan")
        if co.plan
        else (co.labor_plan() if co.started_at is not None else None)
    )
    return {
        "pre_shift": pre_shift,
        "next_day": next_day,
        "next_day_version": co.plan["version"] if co.plan else None,
        "next_day_label": "Next day plan completed"
        if co.plan
        else (
            "Next day plan not yet run — it runs after the final truckfile"
            if co.started_at is None
            else "Next day plan pending (manager builds it at 18:00)"
        ),
        "opportunities": co.opportunities.view(),
        "rotation": {
            "rows": co.rotation,
            "stats": co.rotation_stats,
            "run": bool(co.rotation),
            "max_consecutive": co.cfg.max_consecutive_same_role,
            "disallow_rule": f"heavy path on ≥{cfg.labor_plan.heavy_days_disallow} of the last 3 days (proposed)",
        },
        "ofd_date": co.tomorrow.isoformat(),
    }


# --- cycles / settings / work items / metric specs ---------------------------------------


def cycles_view(tw: StationOpsTwin) -> dict:
    c = tw.config
    on_floor = sum(1 for p in tw.pkgs if p.status == "rolled_over" and p.arrived_at is not None)
    return {
        "banner": (
            f"Pick has been started for {c.cycle.name}, so induct is blocked. Change the cycle, "
            "force-induct late volume, or enable the next cycle."
            if tw.pick_started and not tw._forcing() and not tw.departures_done
            else None
        ),
        "cycles": [
            {
                "cycle": c.cycle.name,
                "assigned_node": c.station_code,
                "force_induct": tw._forcing(),
                "force_until": clock(tw.force_until / 60) if tw.force_until else None,
                "active_until": clock(max(tw.cutoff, tw.force_until or 0) / 60),
                "dynamic_plan": c.cycle.dynamic_plan,
                "induct_blocked": tw.pick_started and not tw._forcing(),
            },
            {
                "cycle": c.cycle.high_value_cycle,
                "assigned_node": c.station_code,
                "force_induct": False,
                "active_until": clock(tw.cutoff / 60),
                "dynamic_plan": False,
                "induct_blocked": tw.pick_started,
            },
            {
                "cycle": "NEXT_DAY",
                "assigned_node": c.station_code,
                "force_induct": False,
                "active_until": clock(tw.next_cycle_until / 60) if tw.next_cycle_until else None,
                "dynamic_plan": True,
                "induct_blocked": not tw._next_cycle_open(),
            },
        ],
        "pick_started": tw.pick_started,
        "pick_start": clock(tw.cutoff / 60),
        "on_floor_missed_cycle": on_floor,
        "next_cycle": tw.counters["next_cycle"],
        "held_wrong_cycle": tw.counters["held_wrong_cycle"],
        "force_staged": tw.counters["force_staged"],
        "changes": tw.cycle_changes,
        "delivery_windows": [
            f"{int(a // 60):02d}:00–{int(b // 60):02d}:00" for a, b in c.cycle.delivery_windows
        ],
        "max_force_induct_minutes": c.cycle.max_force_induct_minutes,
    }


EDITABLE_SETTINGS = (
    "stow_wip_lower_min",
    "stow_wip_upper_min",
    "stow_wip_compliance_target",
    "induct_dwell_minutes",
)


def settings_view(tw: StationOpsTwin) -> dict:
    s = tw.config.settings
    return {
        "values": s.model_dump(),
        "editable": list(EDITABLE_SETTINGS),
        "provenance": {
            "stow_wip_lower_min": "documented default 15",
            "stow_wip_upper_min": "documented default 30",
            "stow_wip_compliance_target": "proposed (network goal unknown)",
            "compliance_interval_minutes": "documented",
            "induct_fph_window_minutes": "documented",
            "belt_gap_defect_seconds": "documented",
            "induct_dwell_minutes": "documented",
            "reinduct_window_before_minutes": "documented",
            "reinduct_window_after_minutes": "documented",
            "fast_start_minutes": "proposed",
            "breaks": "proposed",
            "indirect_allowance": "proposed",
        },
        "site_profile": {
            "sort_start": clock(tw.config.induct.start_minute),
            "pick_start": clock(tw.config.cycle.pick_start_minute),
            "waves": [clock(m) for m in tw.config.outbound.wave_stage_by_minutes],
            "dock_opens": clock(tw.config.induct.start_minute - tw.config.unload_lead_minutes),
            "scale": tw.config.scale,
            "automated_lines": tw.config.induct.automated_lines,
            "lines": tw.config.induct.lines,
        },
    }


def work_items_view(tw: StationOpsTwin) -> dict:
    items = sorted(
        tw.work_items.items,
        key=lambda x: (x["state"] != "pending", x["priority"], -x["created"]),
    )
    return {"summary": tw.work_items.summary(), "items": items[:400]}


def metric_specs() -> dict:
    return {
        k: {"label": v["label"], "status": v["status"], "formula": v["formula"], "unit": v["unit"]}
        for k, v in SPECS.items()
    }


def chapters(tw: StationOpsTwin) -> list[dict]:
    return [{"minute": m, "clock": clock(m), "title": t} for m, t in PITCH_CHAPTERS]


def ageing_v2(tw: StationOpsTwin) -> dict:
    """Forward and reverse ageing by canonical status, with missing / lost reviews."""
    buckets = ["<1 day", "1 day", "2 days", "3 days", "4+ days"]

    def bucket(days: int) -> str:
        return (
            "<1 day"
            if days < 1
            else "4+ days"
            if days >= 4
            else f"{days} day" + ("s" if days > 1 else "")
        )

    fwd: dict[tuple[str, str], Counter] = defaultdict(Counter)
    now = tw.env.now
    for p in tw.pkgs:
        g, sub = st.classify(p, now)
        if g in ("Cancelled",) or sub == "Delivered":
            continue
        fwd[(g, sub)][bucket(1 if p.carryover else 0)] += 1
    for b in tw.backlog:
        if b["resolution"] in ("confirmed_delivered", "found_in_station"):
            continue
        if b["status"] == "marked_missing" or b["resolution"] == "marked_missing":
            key = (
                ("Marked As Lost", "Marked as lost")
                if b["age_days"] >= 4
                else ("Marked As Missing", "Marked as missing")
            )
        elif b["status"] == "retained":
            u = _u("ret", b["tracking_id"])
            sub = (
                "Marked for problem"
                if u < 0.35
                else "Rescheduled"
                if u < 0.5
                else "Pending customer feedback"
                if u < 0.6
                else "Sidelined closed"
            )
            key = ("Retained", sub)
        else:
            key = ("On Road", "In transit (station → customer)")
        fwd[key][bucket(b["age_days"])] += 1
    groups: dict[str, list] = defaultdict(list)
    for (g, sub), cnt in fwd.items():
        groups[g].append(
            {"status": sub, **{x: cnt[x] for x in buckets}, "total": sum(cnt.values())}
        )
    order = [g for g, _ in st.FORWARD_TREE] + ["Retained", "Marked As Missing", "Marked As Lost"]
    forward = [
        {
            "group": g,
            "rows": sorted(groups[g], key=lambda r: -r["total"]),
            **{x: sum(r[x] for r in groups[g]) for x in buckets},
            "total": sum(r["total"] for r in groups[g]),
        }
        for g in order
        if g in groups
    ]
    rev = Counter()
    for p in tw.pkgs:
        if (
            p.attempt_at is not None
            and p.attempt_at <= now
            and (p.delivered is False or p.customer_return)
        ):
            rev["Delivery failed" if p.delivered is False else "Customer return"] += 1
    reverse = [
        {
            "group": "Returns",
            "rows": [
                {"status": k, "<1 day": v, "total": v, **{x: 0 for x in buckets[1:]}}
                for k, v in rev.items()
            ],
            "<1 day": sum(rev.values()),
            **{x: 0 for x in buckets[1:]},
            "total": sum(rev.values()),
        }
    ]
    missing = [
        b
        for b in tw.backlog
        if (b["status"] == "marked_missing" and not b["resolution"])
        or b["resolution"] == "marked_missing"
    ]
    return {
        "buckets": buckets,
        "forward": forward,
        "reverse": reverse,
        "missing_packages": [b for b in missing if b["age_days"] < 4],
        "lost_packages": [b for b in missing if b["age_days"] >= 4],
        "scrubs": tw.scrubs,
    }


def build_views_v2(tw: StationOpsTwin, snap: dict) -> dict:
    return {
        "receive_v2": receive_v2(tw, snap),
        "induct_v2": induct_v2(tw),
        "stow_v2": stow_v2(tw),
        "dwell_v2": {"by_cycle": st.tree(tw, by="cycle"), "by_window": st.tree(tw, by="window")},
        "ageing_v2": ageing_v2(tw),
        "plan_vs_actual": plan_vs_actual(tw),
        "associate_performance": associate_performance(tw),
        "shift_plan_v2": shift_plan_v2(tw),
        "cycles": cycles_view(tw),
        "settings": settings_view(tw),
        "work_items_v2": work_items_view(tw),
        "metric_specs": metric_specs(),
        "chapters": chapters(tw),
    }
