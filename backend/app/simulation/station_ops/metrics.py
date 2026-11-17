"""Metric engine (HANDOFF_V2 E1, ADR-0014).

Every metric is declared with a label, unit, provenance and formula text,
and computed with its *inputs* exposed, so the UI's "How this is calculated"
drawer can show "INC 1,240 ÷ Stow FPH 2,980 × 60 = 25.0 min".

Provenance:
- `documented`: the owner's definitions sheet (generic wording here; no
  tool names). These formulas are implemented exactly.
- `observed`: a label seen on station screens, semantics inferred.
- `proposed`: our assumption; open in docs/OPEN_QUESTIONS.md.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from app.simulation.station_ops.model import StationOpsTwin

D, OBS, P = "documented", "observed", "proposed"

SPECS: dict[str, dict] = {
    # --- documented (owner's definitions) ---------------------------------------
    "stow_wip_minutes": {
        "label": "Stow WIP",
        "unit": "minutes",
        "status": D,
        "formula": "(inducted packages pending stow ÷ Stow FPH) × 60. Thresholds default "
        "15 / 30 min (lower / upper), adjustable in Settings.",
    },
    "stow_wip_compliance": {
        "label": "Est. Stow WIP Compliance",
        "unit": "ratio",
        "status": D,
        "formula": "15-minute intervals with Stow WIP within [lower, upper] ÷ total intervals "
        "× 100%. Target = the network goal (Settings; 70% proposed).",
    },
    "induct_fph": {
        "label": "Induct FPH",
        "unit": "per_hour",
        "status": D,
        "formula": "Actual = inducted volume in the past rolling 10 minutes, expressed per hour. "
        "Target = total volume remaining ÷ remaining belt run time.",
    },
    "stow_fph": {
        "label": "Stow FPH",
        "unit": "per_hour",
        "status": D,
        "formula": "Stowed volume per hour (rolling 10 min × 6). Target = volume left to stow ÷ "
        "remaining belt run time.",
    },
    "belt_run_time": {
        "label": "Belt run time",
        "unit": "hours",
        "status": D,
        "formula": "Sort end − sort start − (fast start + breaks + lunch). Shown as remaining.",
    },
    "total_volume": {
        "label": "Total volume (arrived vs. inducted)",
        "unit": "count",
        "status": D,
        "formula": "Total volume that has arrived on site versus the volume inducted.",
    },
    "inc": {
        "label": "INC",
        "unit": "count",
        "status": D,
        "formula": "Packages with a valid induct scan that are not stowed.",
    },
    "lost_hours": {
        "label": "Lost hours",
        "unit": "hours",
        "status": D,
        "formula": "Gaps between consecutive packages on one belt where 20 s < gap < 120 s "
        "count as downtime defects; their durations are summed per belt and reported in hours.",
    },
    "induct_downtime_dpmo": {
        "label": "Induct downtime DPMO",
        "unit": "dpmo",
        "status": D,
        "formula": "(Total downtime stops ÷ total inducted packages) × 1,000,000. Inclusion "
        "rules for low-volume operators / induct codes: open question Q8.",
    },
    "missed_induct": {
        "label": "Missed induct",
        "unit": "count",
        "status": D,
        "formula": "Packages that missed the induct scan.",
    },
    "induct_dwell": {
        "label": "Induct dwell packages",
        "unit": "count",
        "status": D,
        "formula": "Packages neither inducted nor stowed for more than 60 min, per cluster, "
        "including packages diverted to the jackpot.",
    },
    "tasks_for_psa": {
        "label": "Tasks for PSA",
        "unit": "count",
        "status": D,
        "formula": "Device tasks pending completion by the problem-solve associate.",
    },
    "pending_reinduct": {
        "label": "Pending re-induct",
        "unit": "count",
        "status": D,
        "formula": "Packages marked for reprocess within 60 min before the current induct "
        "cycle ends (at risk of missing on-time re-induct); removed 30 min after it ends.",
    },
    "misdivert_dpmo": {
        "label": "Misdivert DPMO",
        "unit": "dpmo",
        "status": D,
        "formula": "Accumulated misdivert packages ÷ packages not scanned by problem solve × 1e6.",
    },
    "network_missorts": {
        "label": "Network missorts",
        "unit": "count",
        "status": D,
        "formula": "Packages sidelined at induct as wrong station / wrong carrier: pending PS → "
        "pending stow (to the sort-centre-bound container) → resolved.",
    },
    # --- observed on screens (semantics inferred) ---------------------------------
    "fsaf_dpmo": {
        "label": "FSAF DPMO",
        "unit": "dpmo",
        "status": OBS,
        "formula": "First-sort-attempt failures (stower placed on the wrong rack) ÷ stows × 1e6.",
    },
    "spot_check_dpmo": {
        "label": "Spot-check DPMO",
        "unit": "dpmo",
        "status": OBS,
        "formula": "Spot-check defects ÷ spot checks × 1e6 (audit rate proposed).",
    },
}


def _ratio(a: float, b: float) -> float | None:
    return None if b == 0 else a / b


def remaining_volume(tw: StationOpsTwin) -> int:
    """Packages still to induct for the cycle, as the station knows it: the
    manifested volume of trips not cancelled + carry-over + surges, minus
    what is inducted or already out of the cycle."""
    gone = 0
    for p in tw.pkgs:
        if p.inducted_at is not None or p.status in (
            "rolled_over",
            "next_cycle",
            "cancelled_inbound",
            "held_damaged",
            "held_wrong_cycle",
        ):
            gone += 1
    return max(0, len(tw.pkgs) - gone)


def compute(tw: StationOpsTwin) -> dict[str, dict]:  # noqa: C901
    c, st = tw.config, tw.config.settings
    now_min = tw.now_minute
    k = tw.counters
    sort_end = tw.cutoff / 60
    out: dict[str, dict] = {}

    belt_left = tw.belt_run_minutes(now_min, sort_end)
    belt_total = tw.belt_run_minutes(c.induct.start_minute, sort_end)
    out["belt_run_time"] = {
        "value": round(belt_left / 60, 2),
        "target": None,
        "inputs": {
            "sort_start": c.induct.start_minute,
            "sort_end": sort_end,
            "fast_start_min": st.fast_start_minutes,
            "breaks_min": sum(b.minutes for b in st.breaks),
            "total_hours": round(belt_total / 60, 2),
            "remaining_hours": round(belt_left / 60, 2),
        },
    }
    remaining = remaining_volume(tw)
    fph = tw.induct_fph()
    target = remaining / (belt_left / 60) if belt_left > 0 else None
    out["induct_fph"] = {
        "value": round(fph),
        "target": round(target) if target is not None else None,
        "inputs": {
            "window_minutes": st.induct_fph_window_minutes,
            "inducted_in_window": tw.rate_window(tw._inducted_times, st.induct_fph_window_minutes),
            "volume_remaining": remaining,
            "remaining_belt_hours": round(belt_left / 60, 2),
        },
    }
    inc = tw.inc_pending_stow()
    sfph = tw.stow_fph()
    left_to_stow = remaining + inc
    out["stow_fph"] = {
        "value": round(sfph),
        "target": round(left_to_stow / (belt_left / 60)) if belt_left > 0 else None,
        "inputs": {"left_to_stow": left_to_stow, "remaining_belt_hours": round(belt_left / 60, 2)},
    }
    wip = tw.wip_minutes()
    out["stow_wip_minutes"] = {
        "value": None if wip is None else round(wip, 1),
        "target": st.stow_wip_lower_min,
        "target_max": st.stow_wip_upper_min,
        "inputs": {"inc_pending_stow": inc, "stow_fph": round(sfph), "no_flow": wip == 999.0},
    }
    ints = tw.wip_intervals
    out["stow_wip_compliance"] = {
        "value": _ratio(sum(1 for x in ints if x["ok"]), len(ints)),
        "target": st.stow_wip_compliance_target,
        "inputs": {
            "intervals": len(ints),
            "within": sum(1 for x in ints if x["ok"]),
            "lower": st.stow_wip_lower_min,
            "upper": st.stow_wip_upper_min,
            "interval_minutes": st.compliance_interval_minutes,
            "timeline": ints[-40:],
        },
    }
    out["total_volume"] = {
        "value": k["arrived"],
        "target": None,
        "inputs": {"arrived": k["arrived"], "inducted": k["inducted"]},
    }
    out["inc"] = {
        "value": inc,
        "target": None,
        "inputs": {"stow_buffered": tw.n_buffered, "pending_stow": len(tw.stow_q)},
    }

    lines = sorted(set(tw.line_stats) | set(tw.gap_lost_s) | set(range(1, tw.total_lines() + 1)))
    lost_by_line = {tw.line_name(ln): round(tw.gap_lost_s[ln] / 3600, 3) for ln in lines}
    stops_by_line = {tw.line_name(ln): tw.gap_stops[ln] for ln in lines}
    lost = sum(tw.gap_lost_s.values()) / 3600
    stops = sum(tw.gap_stops.values())
    top_lost = sorted(lost_by_line.items(), key=lambda x: -x[1])[:3]
    out["lost_hours"] = {
        "value": round(lost, 2),
        "target": 0,
        "inputs": {
            "by_line": lost_by_line,
            "stops": stops,
            "top_3": top_lost,
            "gap_window_s": list(st.belt_gap_defect_seconds),
        },
    }
    inducted = k["inducted"]
    vol_by_line = {tw.line_name(ln): tw.line_stats[ln]["inducted"] for ln in lines}
    dpmo_by_line = {
        n: round(stops_by_line[n] / vol_by_line[n] * 1e6) if vol_by_line[n] else None
        for n in vol_by_line
    }
    out["induct_downtime_dpmo"] = {
        "value": round(stops / inducted * 1e6) if inducted else None,
        "target": None,
        "inputs": {
            "stops": stops,
            "inducted": inducted,
            "by_line": dpmo_by_line,
            "top_3_by_volume_impact": sorted(stops_by_line.items(), key=lambda x: -x[1])[:3],
        },
    }
    # quality per line (no-read / multi-read / misapplied label) + top impacted line
    quality = []
    for ln in lines:
        ls = tw.line_stats[ln]
        att = ls["attempts"]
        quality.append(
            {
                "line": tw.line_name(ln),
                "automated": tw.is_automated(ln),
                "attempts": att,
                "no_read": _ratio(ls["no_read"], att),
                "multi_read": _ratio(ls["multi_read"], att),
                "misapplied_label": _ratio(ls["misapplied_label"], att),
                "missed_induct": ls["missed_induct"],
            }
        )
    worst = None
    for issue in ("no_read", "multi_read", "misapplied_label"):
        for q in quality:
            if q[issue] and (worst is None or q[issue] > worst[2]):
                worst = (issue, q["line"], q[issue])
    out["quality"] = {
        "value": None,
        "target": None,
        "inputs": {
            "by_line": quality,
            "top_impact": {"issue": worst[0], "line": worst[1], "rate": worst[2]}
            if worst
            else None,
        },
    }
    out["missed_induct"] = {"value": k["missed_induct"], "target": 0, "inputs": {}}

    dwell_min = st.induct_dwell_minutes
    dwell = Counter()
    for p in tw.pkgs:
        if (
            p.arrived_at is not None
            and p.stowed_at is None
            and p.status
            in ("pending_induct", "missed_induct", "problem_solve", "jackpot", "inducting")
            and tw.env.now - p.arrived_at > dwell_min * 60
        ):
            dwell[tw.routes[p.route].cluster] += 1
    out["induct_dwell"] = {
        "value": sum(dwell.values()),
        "target": 0,
        "inputs": {"by_cluster": dict(dwell), "minutes": dwell_min},
    }
    out["tasks_for_psa"] = {"value": len(tw.problem_q), "target": None, "inputs": {}}
    end = sort_end
    in_window = (
        end - st.reinduct_window_before_minutes <= now_min <= end + st.reinduct_window_after_minutes
    )
    pr = sum(
        1
        for p in tw.pkgs
        if p.ps_state == "pending_reinduct"
        and p.status in ("pending_induct", "problem_solve", "rolled_over")
    )
    out["pending_reinduct"] = {
        "value": pr if in_window else 0,
        "target": 0,
        "inputs": {
            "marked_for_reprocess": pr,
            "window_open": in_window,
            "window": [
                end - st.reinduct_window_before_minutes,
                end + st.reinduct_window_after_minutes,
            ],
        },
    }
    mis = Counter(p.misdivert_kind for p in tw.pkgs if p.misdivert_kind)
    not_ps = max(1, inducted - k["problems_resolved"])
    out["misdivert_dpmo"] = {
        "value": round(sum(mis.values()) / not_ps * 1e6) if inducted else None,
        "target": None,
        "inputs": {"by_kind": dict(mis), "stow_scan_to_ps": k["stow_to_ps"], "denominator": not_ps},
    }
    nm = Counter(r["status"] for r in tw.network_missorts)
    reasons = Counter(r["reason"] for r in tw.network_missorts)
    out["network_missorts"] = {
        "value": len(tw.network_missorts),
        "target": None,
        "inputs": {
            "pending_ps": nm["pending_ps"],
            "pending_stow": nm["pending_stow"],
            "resolved": nm["resolved"],
            "by_reason": dict(reasons),
        },
    }
    stows = k["stowed"]
    out["fsaf_dpmo"] = {
        "value": round(k["stower_fsaf"] / stows * 1e6) if stows else None,
        "target": None,
        "inputs": {"fsaf": k["stower_fsaf"], "stows": stows},
    }
    out["spot_check_dpmo"] = {
        "value": round(k["spot_defects"] / k["spot_checks"] * 1e6) if k["spot_checks"] else None,
        "target": None,
        "inputs": {"spot_checks": k["spot_checks"], "defects": k["spot_defects"]},
    }
    return out
