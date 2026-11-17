"""Labor plan v2: work groups and the hourly process-path matrix (HANDOFF_V2
E6, ADR-0016).

Mirrors how a station's shift plan reads, using generic names:
- per cycle: total / planned volume, sideline-RTS, planned rollover;
- show hours vs. needed hours; planned TPH with and without the indirect
  allowance;
- work groups with a time window, attendance %, expected headcount and
  expected show hours;
- an hourly grid of fractional headcount per process path, grouped by
  labour group (Sort, Pick Stage, UTR, Site Support, RTS).

Rates and work-group windows are `proposed` (config.PROCESS_PATHS,
LaborPlanConfig). The volume flowing through each path per hour comes from
the day's linehaul plan and the documented belt-run-time rule: induct runs
at a constant target rate (remaining volume ÷ remaining belt run time).
"""

from __future__ import annotations

import math

from app.simulation.station_ops.config import PROCESS_PATHS, StationOpsConfig

GROUP_ORDER = ("Sort", "Pick Stage", "UTR", "Site Support", "RTS")


def _clock(minute: float) -> str:
    m = int(round(minute)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def hours_axis(cfg: StationOpsConfig) -> list[float]:
    first = min(g.start_minute for g in cfg.labor_plan.work_groups)
    last = max(g.end_minute for g in cfg.labor_plan.work_groups)
    start = math.floor(first / 60) * 60
    return [float(m) for m in range(int(start), int(last), 60)]


def _belt_minutes(cfg: StationOpsConfig, a: float, b: float, sort_end: float) -> float:
    st = cfg.settings
    s0 = cfg.induct.start_minute
    a, b = max(a, s0), min(b, sort_end)
    if b <= a:
        return 0.0
    run = b - a
    run -= max(0.0, min(b, s0 + st.fast_start_minutes) - a)
    for br in st.breaks:
        run -= max(0.0, min(b, br.start_minute + br.minutes) - max(a, br.start_minute))
    return max(0.0, run)


def flows(cfg: StationOpsConfig, volume: float, *, pick_start: float | None = None) -> dict:
    """Volume through each flow driver per hour (planned)."""
    hours = hours_axis(cfg)
    sort_end = pick_start if pick_start is not None else cfg.cycle.pick_start_minute
    total_belt = _belt_minutes(cfg, cfg.induct.start_minute, sort_end, sort_end) or 1.0
    ic = cfg.induct
    auto_cap = ic.automated_lines * ic.automated_rate_pph
    manual_cap = max(0, ic.lines - ic.automated_lines) * ic.rate_pph_per_line
    auto_share = auto_cap / max(1.0, auto_cap + manual_cap) if ic.automated_lines else 0.0
    auto_share = min(auto_share, ic.conveyable_share)
    waves = cfg.outbound.wave_stage_by_minutes
    pick_end = max(waves) if waves else sort_end + 120
    pick_minutes = max(30.0, pick_end - sort_end)
    dock_open = cfg.induct.start_minute - cfg.unload_lead_minutes
    arrivals = [0.0] * len(hours)
    for t in cfg.linehauls:
        if t.cancelled:
            continue
        m = max(dock_open, t.planned_arrival_minute)
        for i, h in enumerate(hours):
            if h <= m < h + 60:
                arrivals[i] += t.volume * volume / max(1, cfg.planned_volume)
                break
    out: dict[str, list[float]] = {
        k: []
        for k in (
            "receive",
            "induct",
            "auto_induct",
            "manual_induct",
            "noncon",
            "stow",
            "pick",
            "hv",
            "rts",
            "auto_line",
            "yard",
        )
    }
    for i, h in enumerate(hours):
        belt = _belt_minutes(cfg, h, h + 60, sort_end)
        ind = volume * belt / total_belt
        out["receive"].append(arrivals[i])
        out["induct"].append(ind)
        out["auto_induct"].append(ind * auto_share)
        out["manual_induct"].append(ind * (1 - auto_share))
        out["noncon"].append(ind * (1 - ic.conveyable_share))
        out["stow"].append(ind * (1 - cfg.quality.high_value_rate))
        pick_overlap = max(0.0, min(h + 60, pick_end) - max(h, sort_end))
        out["pick"].append(volume * pick_overlap / pick_minutes)
        out["hv"].append(ind * cfg.quality.high_value_rate)
        rts_win = [g for g in cfg.labor_plan.work_groups if "rts" in g.paths]
        rts_on = any(g.start_minute <= h < g.end_minute for g in rts_win)
        out["rts"].append(volume * cfg.dispatch.customer_return_rate / 4 if rts_on else 0.0)
        out["auto_line"].append(float(ic.automated_lines) if belt > 0 else 0.0)
        yard_on = any(
            "yard_marshal" in g.paths and g.start_minute <= h < g.end_minute
            for g in cfg.labor_plan.work_groups
        )
        out["yard"].append(float(cfg.dispatch.yard_marshals) if yard_on else 0.0)
    return {"hours": hours, **out}


def needed_matrix(cfg: StationOpsConfig, volume: float, *, pick_start: float | None = None) -> dict:
    """needed[path][hour] = flow ÷ rate (+ fixed headcount)."""
    fl = flows(cfg, volume, pick_start=pick_start)
    hours = fl["hours"]
    paths = {}
    for path, spec in PROCESS_PATHS.items():
        drv = fl[spec["driver"]]
        row = []
        for i in range(len(hours)):
            if spec.get("fixed"):
                hc = spec["fixed"] * drv[i]
            else:
                hc = drv[i] / spec["rate"] if spec["rate"] else 0.0
            row.append(round(hc, 1))
        paths[path] = row
    return {"hours": hours, "paths": paths, "flows": fl}


def build_plan(
    cfg: StationOpsConfig,
    volume: float,
    *,
    scheduled: dict[str, int] | None = None,
    attendance: dict[str, float] | None = None,
    planned_rollover: int = 0,
    sideline_rts: int = 0,
    planned_volume: int | None = None,
    pick_start: float | None = None,
) -> dict:
    nm = needed_matrix(cfg, volume, pick_start=pick_start)
    hours = nm["hours"]
    groups_out = []
    for g in GROUP_ORDER:
        rows = [
            {
                "path": p,
                "label": PROCESS_PATHS[p]["label"],
                "hc": nm["paths"][p],
                "hours": round(sum(nm["paths"][p]), 1),
            }
            for p in PROCESS_PATHS
            if PROCESS_PATHS[p]["group"] == g
        ]
        groups_out.append(
            {
                "group": g,
                "hc": [round(sum(r["hc"][i] for r in rows), 1) for i in range(len(hours))],
                "volume": [
                    round(
                        nm["flows"]["induct"][i]
                        if g == "Sort"
                        else nm["flows"]["pick"][i]
                        if g == "Pick Stage"
                        else 0
                    )
                    for i in range(len(hours))
                ],
                "paths": rows,
            }
        )
    needed_by_hour = [round(sum(gr["hc"][i] for gr in groups_out), 1) for i in range(len(hours))]
    needed_hours = round(sum(needed_by_hour), 1)

    # work groups: scheduled → expected headcount and show hours. Groups with a
    # given roster (the managed crew) come first; every other group is sized to
    # the residual need in its window (fractional hour overlap).
    def frac(h: float, wg) -> float:
        return max(0.0, min(h + 60, wg.end_minute) - max(h, wg.start_minute)) / 60

    avail = [0.0] * len(hours)
    given = scheduled or {}
    ordered = sorted(
        cfg.labor_plan.work_groups, key=lambda w: (w.name not in given, w.start_minute)
    )
    sized: dict[str, dict] = {}
    for wg in ordered:
        att = (attendance or {}).get(wg.name, wg.attendance_rate)
        idx = [i for i, h in enumerate(hours) if frac(h, wg) > 0]
        peak = max((needed_by_hour[i] for i in idx), default=0.0)
        if wg.name in given:
            sched = given[wg.name]
        else:
            resid = max(
                (
                    max(0.0, needed_by_hour[i] - avail[i]) / max(0.25, frac(hours[i], wg))
                    for i in idx
                ),
                default=0.0,
            )
            sched = math.ceil(resid / max(0.5, att) - 0.2) if resid > 0.2 else 0
        exp_hc = sched * att
        for i in idx:
            avail[i] += exp_hc * frac(hours[i], wg)
        win_h = (wg.end_minute - wg.start_minute) / 60
        sized[wg.name] = {
            "name": wg.name,
            "window": f"{_clock(wg.start_minute)} – {_clock(wg.end_minute)}",
            "start_minute": wg.start_minute,
            "end_minute": wg.end_minute,
            "attendance": round(att, 3),
            "scheduled": sched,
            "needed_peak": round(peak, 1),
            "expected_headcount": round(exp_hc, 1),
            "expected_show_hours": round(exp_hc * win_h, 1),
            "paths": wg.paths,
            "roster_given": wg.name in given,
        }
    wgs = [sized[w.name] for w in cfg.labor_plan.work_groups]
    avail = [round(x, 1) for x in avail]
    show_hours = round(sum(w["expected_show_hours"] for w in wgs), 1)
    gap = [round(needed_by_hour[i] - avail[i], 1) for i in range(len(hours))]
    ind = cfg.settings.indirect_allowance
    return {
        "cycles": [
            {
                "cycle": cfg.cycle.name,
                "total_volume": round(volume + planned_rollover + sideline_rts),
                "planned_volume": round(planned_volume if planned_volume is not None else volume),
                "sideline_rts": sideline_rts,
                "planned_rollover": planned_rollover,
            }
        ],
        "totals": {
            "show_hours": show_hours,
            "needed_hours": needed_hours,
            "tph_with_indirect": round(volume / show_hours, 1) if show_hours else None,
            "tph_without_indirect": round(volume / (show_hours * (1 - ind)), 1)
            if show_hours
            else None,
            "indirect_allowance": ind,
        },
        "work_groups": wgs,
        "hours": [f"{_clock(h)}–{_clock(h + 60)}" for h in hours],
        "hour_minutes": hours,
        "total_volume": [round(x) for x in nm["flows"]["receive"]],
        "groups": groups_out,
        "needed_by_hour": needed_by_hour,
        "available_by_hour": avail,
        "gap_by_hour": gap,
        "provenance": "proposed (path rates, work-group windows, attendance)",
    }


def frame_gaps(plan: dict) -> list[dict]:
    """Per work-group frame: worst shortfall (VET) / surplus (VTO) in its window."""
    out = []
    hours = plan["hour_minutes"]
    for wg in plan["work_groups"]:
        idx = [
            i
            for i, h in enumerate(hours)
            if min(h + 60, wg["end_minute"]) - max(h, wg["start_minute"]) >= 30
        ]
        if not idx or not wg.get("roster_given", True):
            continue
        gaps = [plan["gap_by_hour"][i] for i in idx]
        out.append(
            {
                "frame": wg["name"],
                "window": wg["window"],
                "start_minute": wg["start_minute"],
                "end_minute": wg["end_minute"],
                "shortfall": round(max(0.0, max(gaps)), 1),
                "surplus": round(max(0.0, -max(gaps)), 1),
            }
        )
    return out
