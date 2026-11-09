"""Rich, page-level views of the live Station Operations Twin — the data
behind every Station Command screen (performance summary, receive, dwell,
ageing, RTS, sort, stow buffer, associates, pick, stage, dispatch & DSP
coordination with the fictional delivery-area map, high-value cage, labor
plan, problem solve, work items, layout, sort paths, devices) and search.

Everything is computed from the twin's current state on request, so every
page is live. All of it is simulated (`source_kind="simulated"`); the map is
a fictional km grid around the station, never real geography.
"""

import math
from collections import Counter, defaultdict

from app.simulation.station_ops.model import StationOpsTwin, clock, sector_of
from app.simulation.station_ops.snapshot import _ratio

_WINDOWS = (("10–13", 0.0, 0.35), ("13–16", 0.35, 0.65), ("16–19", 0.65, 0.9), ("19–21", 0.9, 1.01))
_PRE_DEPART = ("picked", "staged")
_HELD = ("held_damaged", "problem_solve", "jackpot")


def _mins(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 60, 1)


def _hms(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    s = int(max(0, seconds))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


# --- performance summary ---------------------------------------------------------


def performance(twin: StationOpsTwin) -> dict:
    c, now = twin.config, twin.env.now
    lines = []
    for ln in range(1, twin.total_lines() + 1):
        st = twin.line_stats[ln]
        down = sum(
            max(0.0, min(e, min(twin.cutoff, now)) - max(s, c.induct.start_minute * 60))
            for line, s, e, _ in twin.line_down_windows
            if line == ln
        )
        lost_pkgs = down / 3600 * c.induct.rate_pph_per_line
        att = st["attempts"]
        lines.append(
            {
                "line": f"L{ln}",
                "status": twin.line_down(ln) or "running",
                "inducted": st["inducted"],
                "attempts": att,
                "lost_hours": round(down / 3600, 2),
                "downtime_dpmo": round(lost_pkgs / max(1.0, st["inducted"] + lost_pkgs) * 1e6),
                "no_read_rate": _ratio(st["no_read"], att),
                "multi_read_rate": _ratio(st["multi_read"], att),
                "misapplied_label_rate": _ratio(st["misapplied_label"], att),
                "inductor": next(
                    (
                        a.login
                        for a in twin.assocs
                        if a.present and a.role == "induct" and a.line == ln
                    ),
                    None,
                ),
            }
        )
    issues = []
    for key, label in (
        ("no_read_rate", "No-read"),
        ("multi_read_rate", "Multi-read"),
        ("misapplied_label_rate", "Misapplied label"),
    ):
        worst = max(lines, key=lambda x: x[key] or 0, default=None)
        if worst and (worst[key] or 0) > 0:
            issues.append({"issue": label, "line": worst["line"], "rate": worst[key]})
    return {
        "lines": lines,
        "top_impacted_by_fph": sorted(lines, key=lambda x: x["inducted"])[:3],
        "top_impacted_by_lost_hours": sorted(lines, key=lambda x: -x["lost_hours"])[:3],
        "top_impacted_by_dpmo": sorted(lines, key=lambda x: -x["downtime_dpmo"])[:3],
        "top_quality_issues": sorted(issues, key=lambda x: -x["rate"]),
    }


# --- receive ----------------------------------------------------------------------


def receive(twin: StationOpsTwin, snap: dict) -> dict:
    pk = twin.pkgs
    today_trips = [p for p in pk if p.trip >= 0]
    other = [p for p in pk if p.trip < 0]
    in_transit = sum(1 for p in today_trips if twin.trips[p.trip].status == "in_transit")
    in_yard = sum(1 for p in today_trips if twin.trips[p.trip].status == "in_yard")
    promised = snap["delivery"]["promised"]
    ceiling = snap["metrics"]["dea_ceiling"]["value"] or 0
    return {
        "predicted_dispatch": round(promised * ceiling) + sum(1 for p in other if p.carryover),
        "current_cycle_planned": twin.config.planned_volume,
        "current_cycle_arrived": sum(1 for p in today_trips if p.arrived_at is not None),
        "other_unplanned_arrived": sum(1 for p in other if p.arrived_at is not None),
        "total_arrived": twin.counters["arrived"],
        "manifested": sum(1 for p in pk if p.manifested and p.arrived_at is not None),
        "unplanned_manifested": sum(1 for p in pk if not p.manifested and p.arrived_at is not None),
        "in_transit": in_transit,
        "in_yard": in_yard,
        "marked_for_reprocess": sum(1 for p in pk if p.status == "problem_solve"),
        "inducted": twin.counters["inducted"],
        "doors": [
            {
                "door": d,
                "trip": next(
                    (
                        c.trip_id
                        for i, c in enumerate(twin.config.linehauls)
                        if twin.trips[i].door == d and twin.trips[i].status == "unloading"
                    ),
                    None,
                ),
            }
            for d in range(1, twin.config.doors + 1)
        ],
    }


# --- package summary: dwell / ageing / RTS ---------------------------------------


def _cycle_of(p) -> str:
    if p.hv:
        return "High_Value"
    if not p.manifested or p.carryover:
        return "No Cycle"
    return "CYCLE_1"


def _dwell_status(p) -> str | None:
    s = p.status
    if s == "pending_receive":
        return "Pending Receive"
    if s in ("pending_induct", "inducting"):
        return "Pending Induct"
    if s in ("pending_stow", "stowing", "stowed", "hv_pending_scan_in", "hv_in_cage"):
        return (
            "Pending Stow"
            if s in ("pending_stow", "stowing", "hv_pending_scan_in")
            else "Pending Pick"
        )
    if s in _PRE_DEPART:
        return "Pending Depart"
    if s == "on_road":
        return "On Road"
    if s in _HELD:
        return "Held"
    return None


def dwell(twin: StationOpsTwin) -> dict:
    by_cycle: dict[str, Counter] = defaultdict(Counter)
    by_window: dict[str, Counter] = defaultdict(Counter)
    for p in twin.pkgs:
        st = _dwell_status(p)
        if st is None or p.attempt_at is not None and p.attempt_at <= twin.env.now:
            continue
        by_cycle[st][_cycle_of(p)] += 1
        r = twin.routes[p.route]
        pos = r.packages.index(p.idx) / max(1, len(r.packages))
        win = next(w for w, lo, hi in _WINDOWS if lo <= pos < hi)
        by_window[st][win] += 1
    order = [
        "Pending Receive",
        "Pending Induct",
        "Pending Stow",
        "Pending Pick",
        "Pending Depart",
        "On Road",
        "Held",
    ]
    return {
        "columns": ["No Cycle", "CYCLE_1", "High_Value"],
        "by_cycle": [
            {"status": s, **{c: by_cycle[s][c] for c in ("No Cycle", "CYCLE_1", "High_Value")}}
            for s in order
        ],
        "windows": [w for w, _, _ in _WINDOWS],
        "by_window": [{"status": s, **{w: by_window[s][w] for w, _, _ in _WINDOWS}} for s in order],
    }


def _age_bucket(days: int) -> str:
    return (
        "<1 day"
        if days < 1
        else "4+ days"
        if days >= 4
        else f"{days} day" + ("s" if days > 1 else "")
    )


def ageing(twin: StationOpsTwin) -> dict:
    rows: dict[str, Counter] = defaultdict(Counter)
    for p in twin.pkgs:
        s = p.status
        group = (
            "Inbound"
            if s in ("pending_receive", "pending_induct")
            else "Induct"
            if s in ("inducting", "problem_solve")
            else "Stow"
            if s
            in ("pending_stow", "stowing", "stowed", "jackpot", "hv_pending_scan_in", "hv_in_cage")
            else "Pick and Stage"
            if s in _PRE_DEPART
            else "On Road"
            if s == "on_road" and not (p.attempt_at and p.attempt_at <= twin.env.now)
            else "Retained"
            if s in ("rolled_over", "held_damaged", "left_behind")
            else None
        )
        if group:
            rows[group][_age_bucket(1 if p.carryover else 0)] += 1
    for b in twin.backlog:
        if b["resolution"] in ("confirmed_delivered", "found_in_station"):
            continue
        status = (
            "Marked As Missing"
            if (b["status"] == "marked_missing" or b["resolution"] == "marked_missing")
            else "Retained"
            if b["status"] == "retained"
            else "On Road"
        )
        rows[status][_age_bucket(b["age_days"])] += 1
    buckets = ["<1 day", "1 day", "2 days", "3 days", "4+ days"]
    order = [
        "Inbound",
        "Induct",
        "Stow",
        "Pick and Stage",
        "On Road",
        "Retained",
        "Marked As Missing",
    ]
    missing = [
        b
        for b in twin.backlog
        if (b["status"] == "marked_missing" and not b["resolution"])
        or b["resolution"] == "marked_missing"
    ]
    return {
        "buckets": buckets,
        "rows": [
            {"status": s, **{b: rows[s][b] for b in buckets}, "total": sum(rows[s].values())}
            for s in order
        ],
        "missing_packages": [b for b in missing if b["age_days"] < 4],
        "lost_packages": [b for b in missing if b["age_days"] >= 4],
        "scrubs": twin.scrubs,
    }


def rts(twin: StationOpsTwin) -> dict:
    now = twin.env.now
    inbound = Counter()
    at_station = Counter()
    for r in twin.routes:
        if r.driver is None or r.departed_at is None:
            continue
        d = twin.drivers[r.driver]
        returned = d.return_at is not None and d.return_at <= now
        fails = sum(
            1
            for i in r.packages
            if twin.pkgs[i].attempt_at
            and twin.pkgs[i].attempt_at <= now
            and twin.pkgs[i].delivered is False
        )
        not_att = r.not_attempted if (returned or now > r.departed_at) else 0
        returns = sum(
            1
            for i in r.packages
            if twin.pkgs[i].customer_return
            and twin.pkgs[i].attempt_at
            and twin.pkgs[i].attempt_at <= now
        )
        tgt = at_station if returned else inbound
        tgt["Undeliverable"] += fails
        tgt["Not attempted"] += not_att
        tgt["Customer return"] += returns
    cancelled = sum(1 for p in twin.pkgs if p.status == "held_damaged")
    return {
        "types": ["Undeliverable", "Not attempted", "Customer return"],
        "inbound": dict(inbound),
        "currently_at_station": dict(at_station),
        "delivery_cancelled": cancelled,
        "totals": {
            "inbound": sum(inbound.values()),
            "at_station": sum(at_station.values()),
            "delivery_cancelled": cancelled,
        },
    }


# --- sort / stow ---------------------------------------------------------------


def stow_buffers(twin: StationOpsTwin) -> list[dict]:
    now = twin.env.now
    hours = max(0.25, (min(now, twin.cutoff) - twin.config.induct.start_minute * 60) / 3600)
    total_stowed = max(1, twin.counters["stowed"])
    out = []
    for cl in twin.config.sort.clusters:
        st = twin.cluster_stats[cl]
        aisles = [a for a in twin.aisles if a.startswith(cl)]
        level = sum(twin.aisle_level[a] for a in aisles)
        cap = sum(twin.aisle_capacity.get(a, 0) for a in aisles)
        full = sum(1 for a in aisles if twin.aisle_level[a] >= twin.aisle_capacity.get(a, 10**9))
        nr = sum(
            1 for p in twin.pkgs if p.problem == "no_read" and twin.routes[p.route].cluster == cl
        )
        out.append(
            {
                "buffer": f"BUFFER-{cl}",
                "status": "active" if not twin.pick_started else "picking",
                "full_bays": full,
                "bays": len(aisles),
                "jackpot": st["jackpot"],
                "jackpot_rate": _ratio(st["jackpot"], st["stowed"] + st["jackpot"]),
                "no_read_rate": _ratio(nr, max(1, st["stowed"])),
                "current_volume": level,
                "capacity": cap,
                "pct_station_volume": st["stowed"] / total_stowed,
                "avg_pph": round(st["stowed"] / hours),
            }
        )
    return out


def associates(twin: StationOpsTwin) -> dict:
    now = twin.env.now
    rows = []
    for a in twin.assocs:
        busy_h = a.busy_s / 3600
        idle_now = (now - a.idle_since) if a.idle_since is not None else 0.0
        rows.append(
            {
                "login": a.login,
                "role": a.role,
                "home_role": a.home_role,
                "present": a.present,
                "vet": a.vet,
                "task": a.task,
                "task_ref": a.task_ref,
                "picklist": a.task_ref if a.task in ("picking", "staging") else None,
                "time_since_last_activity": _hms(now - a.last_activity)
                if a.last_activity
                else None,
                "current_task_duration": _hms(now - a.task_started)
                if a.task_started and a.task not in ("idle", "off_shift")
                else None,
                "idle_total": _hms(a.idle_s + idle_now),
                "longest_idle": _hms(max(a.longest_idle_s, idle_now)),
                "units": a.units,
                "pph": round(a.units / busy_h) if busy_h > 0.05 else None,
                "skill": round(a.skill, 2),
                "location": a.location,
                "line": a.line,
                "shift_start": clock(a.shift_start / 60),
                "rotation": [{"clock": clock(m), "role": r} for m, r in a.history],
            }
        )
    present = [r for r in rows if r["present"]]
    working = [r for r in present if r["task"] not in ("idle", "off_shift")]
    return {
        "rows": rows,
        "summary": {
            "total": len(present),
            "with_task": len(working),
            "idle": sum(1 for r in present if r["task"] == "idle"),
            "absent": sum(1 for r in rows if not r["present"]),
            "vet": sum(1 for r in rows if r["vet"]),
            "by_role": dict(Counter(r["role"] for r in present)),
        },
    }


# --- outbound: pick / stage / dispatch ---------------------------------------------


def pick_summary(snap: dict) -> dict:
    rs = snap["routes"]
    durations = [r["pick_minutes"] for r in rs if r["pick_minutes"]]
    return {
        "total_routes": len(rs),
        "not_ready": sum(1 for r in rs if r["status"] == "not_ready"),
        "not_assigned": sum(1 for r in rs if r["status"] == "ready" and not r["sidelined"]),
        "in_progress": sum(1 for r in rs if r["status"] == "picking"),
        "partially_picked": sum(1 for r in rs if r["status"] == "staging"),
        "picked": sum(1 for r in rs if r["status"] in ("staged", "loading", "departed")),
        "sidelined": sum(1 for r in rs if r["sidelined"]),
        "high_spr": sum(1 for r in rs if r["spr_flag"] == "high"),
        "avg_pick_minutes": round(sum(durations) / len(durations), 1) if durations else None,
    }


def stage_summary(snap: dict) -> dict:
    rs = snap["routes"]
    return {
        "total_routes": len(rs),
        "timely_staged": snap["metrics"]["timely_staged"]["value"],
        "not_ready": sum(1 for r in rs if r["status"] in ("not_ready", "ready", "picking")),
        "partially_staged": sum(1 for r in rs if r["status"] == "staging"),
        "staged": sum(1 for r in rs if r["status"] in ("staged", "loading")),
        "departed": sum(1 for r in rs if r["status"] == "departed"),
    }


def _driver_pos(twin: StationOpsTwin, d) -> tuple[float, float]:
    now = twin.env.now
    r = twin.routes[d.route]
    if d.state == "off_duty" or d.state == "released":
        return d.home
    if d.state == "en_route" and d.leave_at is not None:
        f = min(1.0, (now - d.leave_at) / max(1.0, d.travel_s + d.extra_travel_s))
        return (d.home[0] * (1 - f), d.home[1] * (1 - f))
    if d.state == "on_road" and d.departed_at is not None:
        total = r.duration_hours * 3600
        f = (now - d.departed_at) / total
        th = math.radians(r.angle)
        cx, cy = r.radius_km * math.cos(th), r.radius_km * math.sin(th)
        if f >= 1.0:
            back = min(1.0, (now - d.departed_at - total) / (20 * 60))
            return (cx * (1 - back), cy * (1 - back))
        if f < 0.12:
            return (cx * f / 0.12, cy * f / 0.12)
        if f > 0.92:
            return (cx * (1 - (f - 0.92) / 0.08 * 0.5), cy * (1 - (f - 0.92) / 0.08 * 0.5))
        phase = (f - 0.12) / 0.8 * 2 * math.pi
        rad = 1.6
        return (cx + rad * math.cos(phase + th), cy + rad * math.sin(phase + th))
    return (0.0, 0.0)


def dispatch(twin: StationOpsTwin) -> dict:
    now = twin.env.now
    tol = twin.config.dispatch.otd_tolerance_minutes * 60
    drivers = []
    for d in twin.drivers:
        if d.state == "released":
            continue
        r = twin.routes[d.route]
        x, y = _driver_pos(twin, d)
        stops_done = 0
        if d.departed_at is not None:
            stops_done = min(
                r.stops, int(r.stops * max(0.0, now - d.departed_at) / (r.duration_hours * 3600))
            )
        returned = d.return_at is not None and d.return_at <= now
        state = d.state
        if state == "on_road" and returned:
            state = (
                "finished" if d.swiped_at is not None and d.swiped_at <= now else "pending_swipe"
            )
        due = r.planned_depart - twin.config.dispatch.check_in_lead_minutes * 60
        drivers.append(
            {
                "driver_id": d.driver_id,
                "dsp": d.dsp,
                "route_id": r.route_id,
                "state": state,
                "standby": d.standby,
                "notified": d.notified_at is not None,
                "check_in_due": clock(due / 60),
                "expected_check_in": clock(twin.driver_expected_checkin(d) / 60)
                if d.arrived_at is None
                else None,
                "checked_in_at": clock(d.arrived_at / 60) if d.arrived_at else None,
                "late_by": round(twin.driver_late_by(d), 1)
                if state in ("off_duty", "en_route")
                else (round(max(0.0, (d.arrived_at - due) / 60), 1) if d.arrived_at else None),
                "no_show_suspected": state == "off_duty"
                and now > twin.planned_leave(d) + 15 * 60
                and d.leave_at is None,
                "departed_at": clock(d.departed_at / 60) if d.departed_at else None,
                "stops_done": stops_done,
                "stops_total": r.stops,
                "failed": r.failed,
                "return_at": clock(d.return_at / 60) if d.return_at else None,
                "swiped": d.swiped_at is not None and d.swiped_at <= now,
                "x": round(x, 2),
                "y": round(y, 2),
                "sector": sector_of(*d.home),
            }
        )
    dsps = []
    for cfg in twin.config.dispatch.dsps:
        rs = [r for r in twin.routes if r.dsp == cfg.code]
        dep = [r for r in rs if r.departed_at is not None]
        ds = [x for x in drivers if x["dsp"] == cfg.code]
        dsps.append(
            {
                "dsp": cfg.code,
                "routes": len(rs),
                "departed": len(dep),
                "on_time": sum(1 for r in dep if r.departed_at <= r.planned_depart + tol),
                "otd": _ratio(
                    sum(1 for r in dep if r.departed_at <= r.planned_depart + tol), len(dep)
                ),
                "checked_in": sum(1 for x in ds if x["state"] in ("checked_in", "loading")),
                "en_route": sum(1 for x in ds if x["state"] == "en_route"),
                "late": sum(
                    1
                    for x in ds
                    if (x["late_by"] or 0) > 0 and x["state"] in ("off_duty", "en_route")
                ),
                "no_show_suspected": sum(1 for x in ds if x["no_show_suspected"]),
                "pending_swipe": sum(1 for x in ds if x["state"] == "pending_swipe"),
                "standby_remaining": twin.standby_remaining.get(cfg.code, 0),
                "late_rate_plan": cfg.late_rate,
            }
        )
    zones = [
        {
            "route_id": r.route_id,
            "x": round(r.radius_km * math.cos(math.radians(r.angle)), 2),
            "y": round(r.radius_km * math.sin(math.radians(r.angle)), 2),
            "dsp": r.dsp,
        }
        for r in twin.routes
    ]
    incidents = [
        d for d in twin.disruptions_seen if d["kind"] == "traffic_incident" and d["to"] > now
    ]
    return {
        "dsps": dsps,
        "drivers": drivers,
        "map": {"zones": zones, "incidents": incidents, "extent_km": 26},
    }


# --- high value -----------------------------------------------------------------


def high_value(twin: StationOpsTwin) -> dict:
    now = twin.env.now
    hv = [p for p in twin.pkgs if p.hv]
    st = Counter(p.status for p in hv)
    in_cage = [p for p in hv if p.status == "hv_in_cage"]
    dwell = [now - p.stowed_at for p in in_cage if p.stowed_at]
    disp = [p for p in hv if p.departed_at is not None]
    rows = []
    for p in sorted(hv, key=lambda x: x.idx)[:300]:
        rows.append(
            {
                "tracking_id": p.tracking_id,
                "route_id": twin.routes[p.route].route_id,
                "status": p.status,
                "custody_scans": p.custody_scans,
                "location": p.location,
                "cage_minutes": _mins(now - p.stowed_at)
                if p.status == "hv_in_cage" and p.stowed_at
                else None,
            }
        )
    return {
        "total": len(hv),
        "pending_scan_in": st["hv_pending_scan_in"],
        "in_cage": st["hv_in_cage"],
        "handed_off": twin.counters["hv_handed_off"],
        "dispatched": len(disp),
        "rolled_over": st["rolled_over"],
        "custody_compliance": _ratio(sum(1 for p in disp if p.custody_scans >= 2), len(disp)),
        "avg_cage_dwell_minutes": round(sum(dwell) / len(dwell) / 60, 1) if dwell else None,
        "queue": len(twin.hv_q),
        "associates": [a.login for a in twin.assocs if a.present and a.role == "high_value"],
        "packages": rows,
    }


# --- labor plan -------------------------------------------------------------------


def labor_plan(twin: StationOpsTwin, snap: dict) -> dict:
    c = twin.config
    lab = c.labor
    volume = c.planned_volume + sum(1 for p in twin.pkgs if p.carryover)
    forecast_unplanned = round(volume * c.quality.unmanifested_rate)
    total = volume + forecast_unplanned
    sidelined = sum(len(r.packages) for r in twin.routes if r.sidelined)
    promised = snap["delivery"]["promised"]
    planned_rollover = round(promised * (1 - (snap["metrics"]["dea_ceiling"]["value"] or 1)))
    induct_window_h = (twin.cutoff / 60 - c.induct.start_minute) / 60
    needed = {
        "Induct": total / c.induct.rate_pph_per_line,
        "Stow": total / c.stow.rate_pph_per_stower,
        "Pick & Stage": total * lab.pick_seconds_per_package / 3600
        + len(twin.routes) * (lab.pick_base_minutes + lab.stage_minutes_per_cart * 2) / 60,
        "Problem Solve": total * 0.02 * 3.5 / 60,
        "High Value": total
        * c.quality.high_value_rate
        * (c.quality.hv_scan_in_seconds + c.quality.hv_handoff_seconds)
        / 3600,
    }
    groups = Counter(a.home_role for a in twin.assocs if not a.vet)
    present = Counter(a.home_role for a in twin.assocs if not a.vet and a.present)
    pick_h = 2.5
    hours = {
        "induct": induct_window_h,
        "stow": induct_window_h,
        "problem_solve": induct_window_h + pick_h,
        "high_value": induct_window_h + pick_h,
        "pick": pick_h,
    }
    windows = {
        "induct": (c.induct.start_minute, twin.cutoff / 60),
        "stow": (c.induct.start_minute, twin.cutoff / 60),
        "problem_solve": (c.induct.start_minute, twin.cutoff / 60 + 150),
        "high_value": (c.induct.start_minute, twin.cutoff / 60 + 150),
        "pick": (twin.cutoff / 60 - 15, twin.cutoff / 60 + 150),
    }
    rows = []
    for role, n in groups.items():
        lo, hi = windows[role]
        rows.append(
            {
                "time": f"{clock(lo)} - {clock(hi)}",
                "work_group": role.replace("_", " ").title(),
                "attendance": _ratio(present[role], n),
                "expected_headcount": n,
                "present": present[role],
                "expected_show_hours": round(present[role] * hours[role], 1),
            }
        )
    show = sum(r["expected_show_hours"] for r in rows) + sum(
        (twin.cutoff / 60 + 150 - a.shift_start / 60) / 60 for a in twin.assocs if a.vet
    )
    need = sum(needed.values())
    gap = need - show
    shift_h = 6.5
    return {
        "ofd_date": c.ofd_date.isoformat(),
        "cycle": c.cycle.name,
        "total_volume": total,
        "planned_volume": volume,
        "forecast_unplanned": forecast_unplanned,
        "sideline_rts": sidelined,
        "planned_rollover": planned_rollover,
        "total_show_hours": round(show, 1),
        "total_needed_hours": round(need, 1),
        "needed_by_function": {k: round(v, 1) for k, v in needed.items()},
        "planned_tph": round(total / max(1.0, show), 1),
        "work_groups": rows,
        "vet_opportunities": max(0, min(twin.flex_remaining, math.ceil(gap / shift_h)))
        if gap > 0
        else 0,
        "vto_opportunities": max(0, math.floor(-gap / shift_h)) if gap < 0 else 0,
        "flex_remaining": twin.flex_remaining,
    }


# --- problem solve / work items / layout / devices ----------------------------------


def problem_solve(twin: StationOpsTwin) -> dict:
    items = twin.problem_q.items()
    reasons = Counter(
        "jackpot" if k == "jackpot" else (twin.pkgs[i].problem or "other") for k, i in items
    )
    return {
        "queue": len(items),
        "by_reason": dict(reasons),
        "resolved": twin.counters["problems_resolved"],
        "associates": [a.login for a in twin.assocs if a.present and a.role == "problem_solve"],
        "items": [
            {
                "tracking_id": twin.pkgs[i].tracking_id,
                "reason": "jackpot" if k == "jackpot" else twin.pkgs[i].problem,
                "route_id": twin.routes[twin.pkgs[i].route].route_id,
            }
            for k, i in items[:100]
        ],
    }


def work_items(twin: StationOpsTwin, snap: dict, disp: dict) -> list[dict]:
    items = []
    ps = len(twin.problem_q)
    if ps:
        items.append(
            {
                "area": "Problem solve",
                "priority": "high" if ps > 40 else "normal",
                "title": f"Clear {ps} problem-solve package(s)",
                "action": None,
            }
        )
    if snap["sort"]["jackpot"] and not twin.pick_started:
        items.append(
            {
                "area": "Stow",
                "priority": "normal",
                "title": "Jackpot overflow active — check full bays",
                "action": None,
            }
        )
    for r in snap["routes"]:
        if r["at_risk"] and r["status"] in ("not_ready", "ready"):
            items.append(
                {
                    "area": "Pick",
                    "priority": "high",
                    "title": f"{r['route_id']} at risk of stage-by "
                    f"{r['stage_by']} (projected {r['projected_stage_at']})",
                    "action": {"kind": "prioritize_route", "target": r["route_id"]},
                }
            )
    for d in disp["drivers"]:
        if d["no_show_suspected"]:
            items.append(
                {
                    "area": "Dispatch",
                    "priority": "high",
                    "title": f"{d['driver_id']} ({d['dsp']}) has not left for {d['route_id']}",
                    "action": {"kind": "reassign_standby", "target": d["route_id"]},
                }
            )
        elif (d["late_by"] or 0) > 5 and not d["notified"]:
            items.append(
                {
                    "area": "Dispatch",
                    "priority": "normal",
                    "title": f"{d['driver_id']} projected {d['late_by']:.0f} min late "
                    f"for {d['route_id']}",
                    "action": {"kind": "notify_drivers", "target": d["route_id"]},
                }
            )
    pending_swipe = sum(1 for d in disp["drivers"] if d["state"] == "pending_swipe")
    if pending_swipe:
        items.append(
            {
                "area": "Dispatch",
                "priority": "normal",
                "title": f"{pending_swipe} returned driver(s) haven't swiped to finish",
                "action": {"kind": "notify_swipe_finish"},
            }
        )
    missing = sum(
        1 for b in twin.backlog if b["status"] == "marked_missing" and not b["resolution"]
    )
    if missing and not any(s["kind"] == "in_station" for s in twin.scrubs):
        items.append(
            {
                "area": "Package summary",
                "priority": "normal",
                "title": f"{missing} package(s) marked missing — run an in-station scrub",
                "action": {"kind": "start_scrub", "target": "in_station"},
            }
        )
    if len(twin.hv_q) > 15:
        items.append(
            {
                "area": "High value",
                "priority": "high",
                "title": f"{len(twin.hv_q)} high-value tasks waiting at the cage",
                "action": {
                    "kind": "move_associates",
                    "target": "high_value",
                    "params": {"from_role": "problem_solve"},
                    "amount": 1,
                },
            }
        )
    return items


def layout(twin: StationOpsTwin, snap: dict) -> dict:
    staging = {r["staging_location"]: r["status"] for r in snap["routes"]}
    return {
        "aisles": [
            {"aisle": a, "level": twin.aisle_level[a], "capacity": twin.aisle_capacity.get(a, 0)}
            for a in twin.aisles
        ],
        "staging": [{"location": k, "status": v} for k, v in sorted(staging.items())],
        "doors": receive(twin, snap)["doors"],
        "lines": [
            {"line": f"L{ln}", "status": twin.line_down(ln) or "running"}
            for ln in range(1, twin.total_lines() + 1)
        ],
    }


def sort_paths(twin: StationOpsTwin) -> list[dict]:
    cl = twin.config.sort.clusters
    sidelined = [r.route_id for r in twin.routes if r.sidelined]
    return [
        {
            "partition": twin.config.cycle.name,
            "cycle": twin.config.cycle.name,
            "grid": f"{cl[0]}01–{cl[-1]}{twin.config.sort.aisles_per_cluster:02d}",
            "overlaps": ["HIGH_VALUE", "SIDELINE"],
        },
        {
            "partition": "HIGH_VALUE",
            "cycle": "High_Value",
            "grid": "HV-CAGE",
            "overlaps": [twin.config.cycle.name],
        },
        {
            "partition": "OVERFLOW",
            "cycle": twin.config.cycle.name,
            "grid": ", ".join(f"OVERFLOW-{c}" for c in cl),
            "overlaps": [twin.config.cycle.name],
        },
        {
            "partition": "SIDELINE",
            "cycle": "—",
            "grid": f"{len(sidelined)} route(s)",
            "overlaps": sidelined[:6],
        },
    ]


def devices(twin: StationOpsTwin) -> dict:
    now = twin.env.now
    handhelds = []
    for a in twin.assocs:
        if not a.present or now < a.shift_start:
            continue
        on_h = (now - a.shift_start) / 3600
        battery = max(3, round(100 - a.busy_s / 3600 * 9 - max(0.0, on_h - a.busy_s / 3600) * 3))
        handhelds.append(
            {
                "device": f"HH-{a.idx:03d}",
                "assigned_to": a.login,
                "battery": battery,
                "status": "low_battery" if battery < 20 else "online",
            }
        )
    tunnels = [
        {
            "device": f"SCAN-L{ln}",
            "read_rate": 1 - (twin.config.induct.no_read_rate * twin._scanner_factor(ln)),
            "status": "degraded"
            if twin._scanner_factor(ln) > 1
            else ("down" if twin.line_down(ln) else "online"),
        }
        for ln in range(1, twin.total_lines() + 1)
    ]
    return {"handhelds": handhelds, "scanners": tunnels}


def build_views(twin: StationOpsTwin, snap: dict) -> dict:
    disp = dispatch(twin)
    return {
        "performance": performance(twin),
        "receive": receive(twin, snap),
        "dwell": dwell(twin),
        "ageing": ageing(twin),
        "rts": rts(twin),
        "stow_buffers": stow_buffers(twin),
        "associates": associates(twin),
        "pick": pick_summary(snap),
        "stage": stage_summary(snap),
        "dispatch": disp,
        "high_value": high_value(twin),
        "labor_plan": labor_plan(twin, snap),
        "problem_solve": problem_solve(twin),
        "work_items": work_items(twin, snap, disp),
        "layout": layout(twin, snap),
        "sort_paths": sort_paths(twin),
        "devices": devices(twin),
        "events": list(twin.events)[-120:],
    }


def search(twin: StationOpsTwin, query: str) -> dict:
    q = query.strip().upper()
    now = twin.env.now
    if not q:
        return {"kind": "none", "results": []}
    pkgs = [p for p in twin.pkgs if p.tracking_id == q or q in p.tracking_id][:20]
    if pkgs:
        return {
            "kind": "package",
            "results": [
                {
                    "tracking_id": p.tracking_id,
                    "status": p.status,
                    "route_id": twin.routes[p.route].route_id,
                    "cycle": _cycle_of(p),
                    "high_value": p.hv,
                    "location": p.location,
                    "timeline": [
                        {"event": ev, "clock": clock(t / 60)}
                        for ev, t in (
                            ("arrived", p.arrived_at),
                            ("inducted", p.inducted_at),
                            ("stowed/caged", p.stowed_at),
                            ("picked", p.picked_at),
                            ("staged", p.staged_at),
                            ("departed", p.departed_at),
                            (
                                "delivery attempt",
                                p.attempt_at if p.attempt_at and p.attempt_at <= now else None,
                            ),
                        )
                        if t is not None
                    ],
                    "delivered": p.delivered if p.attempt_at and p.attempt_at <= now else None,
                }
                for p in pkgs
            ],
        }
    r = twin.route_by_id(q)
    if r:
        return {
            "kind": "container",
            "results": [
                {
                    "route_id": r.route_id,
                    "status": r.status,
                    "aisle": r.aisle,
                    "staging": r.staging_location,
                    "packages": len(r.packages),
                    "bags": r.bags,
                    "carts": r.carts,
                    "dsp": r.dsp,
                    "driver": twin.drivers[r.driver].driver_id if r.driver is not None else None,
                }
            ],
        }
    assoc = [a for a in twin.assocs if q.lower() in a.login.lower()]
    if assoc:
        return {
            "kind": "associate",
            "results": [
                x for x in associates(twin)["rows"] if x["login"] in {a.login for a in assoc}
            ],
        }
    return {"kind": "none", "results": []}
