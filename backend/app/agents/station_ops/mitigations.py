"""What each specialist agent can do about each risk.

Three kinds of response:
- *reflex* actions — cheap, low-risk, well-understood coordination (notify a
  late driver, prioritise an at-risk route, send a standby for a no-show,
  remind drivers to swipe). Taken immediately, no simulation needed, always
  logged. A good dispatcher does these without a meeting.
- *planned* levers — consume a scarce resource or trade one metric for
  another (VET call-ins from the finite flex pool, moving associates between
  functions, opening a spare line, moving pick start). Evaluated by robust
  counterfactual simulation before use.
- *advisory* — no lever exists in the twin (scanner audits, sort audits);
  surfaced as recommendations, never scored with invented numbers.

LEVER_LIMITS doubles as the policy-engine bound for `station_ops_mitigation`
decisions (app/security/policy_engine.py).
"""

from pydantic import BaseModel

from app.simulation.station_ops.model import (
    MAX_CUTOFF_EXTENSION_MINUTES,
    Intervention,
    StationOpsTwin,
)

LEVER_LIMITS: dict[str, float] = {
    "add_stowers": 6,
    "add_pickers": 6,
    "open_induct_line": 1,
    "extend_cutoff": MAX_CUTOFF_EXTENSION_MINUTES,
    "priority_late_linehauls": 1,
    "move_associates": 4,
    "resequence_unload": 1,
    "prioritize_route": 10,
    "sideline_route": 1,
    "unsideline_route": 1,
    "move_route_wave": 2,
    "notify_drivers": 1,
    "reassign_standby": 1,
    "notify_swipe_finish": 1,
    "start_scrub": 1,
    "restage_cart": 1,
    "direct_sweep": 1,
    "request_replacement_van": 1,
    "add_yard_marshal": 1,
    "check_ferry": 1,
    "draft_gtdr": 1,
    "replan_next_day": 1,
    "offer_vet": 12,
    "offer_vto": 12,
    # v2
    "force_induct": 30,
    "change_cycle": 1,
    "enable_cycle": 8,
    "rebalance_finger": 1,
    "approve_damaged": 1,
    "watch_trip": 1,
    "post_opportunity": 12,
    "close_window": 1,
    "rerun_rotation": 1,
}

# (kind, amount, params) — a candidate is a list of these applied together.
Spec = tuple[str, float, dict]
_C = {
    "late_linehaul_rollover": [
        [("extend_cutoff", 15, {})],
        [("extend_cutoff", 30, {}), ("add_pickers", 3, {})],
        [("extend_cutoff", 45, {}), ("add_pickers", 5, {})],
        [("priority_late_linehauls", 1, {})],
        [("open_induct_line", 1, {}), ("add_stowers", 2, {})],
    ],
    "yard_congestion": [[("priority_late_linehauls", 1, {})]],
    "induct_capacity_shortfall": [
        [("open_induct_line", 1, {})],
        [("open_induct_line", 1, {}), ("add_stowers", 2, {})],
        [("extend_cutoff", 15, {})],
        [("extend_cutoff", 30, {}), ("add_pickers", 3, {})],
    ],
    "induct_line_down": [
        [("open_induct_line", 1, {})],
        [("open_induct_line", 1, {}), ("add_stowers", 2, {})],
    ],
    "stow_capacity_shortfall": [
        [("add_stowers", 2, {})],
        [("add_stowers", 4, {})],
        [("add_stowers", 6, {})],
        [("move_associates", 1, {"from_role": "problem_solve", "to_role": "stow"})],
        [("extend_cutoff", 15, {}), ("add_stowers", 2, {})],
    ],
    "stow_wip_above_band": [
        [("add_stowers", 2, {})],
        [("add_stowers", 4, {})],
        [("move_associates", 1, {"from_role": "problem_solve", "to_role": "stow"})],
    ],
    "stow_wip_below_band": [
        [("move_associates", 1, {"from_role": "stow", "to_role": "problem_solve"})],
        [("move_associates", 1, {"from_role": "stow", "to_role": "high_value"})],
    ],
    "problem_solve_backlog": [
        [("move_associates", 1, {"from_role": "stow", "to_role": "problem_solve"})],
        [
            ("move_associates", 2, {"from_role": "stow", "to_role": "problem_solve"}),
            ("add_stowers", 2, {}),
        ],
    ],
    "induct_below_dynamic_target": [
        [("open_induct_line", 1, {})],
        [("open_induct_line", 1, {}), ("add_stowers", 2, {})],
        [("extend_cutoff", 15, {})],
    ],
    "late_volume_at_pick_start": [
        [("force_induct", 15, {})],
        [("force_induct", 30, {})],
        [("extend_cutoff", 15, {})],
        [("extend_cutoff", 15, {}), ("force_induct", 15, {})],
    ],
    "induct_dwell_over_60": [
        [("move_associates", 1, {"from_role": "stow", "to_role": "problem_solve"})],
        [("move_associates", 2, {"from_role": "stow", "to_role": "problem_solve"})],
    ],
    "pending_reinduct_at_risk": [
        [("move_associates", 1, {"from_role": "stow", "to_role": "problem_solve"})],
        [("force_induct", 15, {})],
    ],
    "unplanned_surge": [
        [("add_stowers", 2, {})],
        [("open_induct_line", 1, {}), ("add_stowers", 2, {})],
    ],
    "routes_at_risk": [
        [("add_pickers", 2, {})],
        [("add_pickers", 4, {})],
        [("move_associates", 1, {"from_role": "problem_solve", "to_role": "pick"})],
    ],
}

#: Risks where "do no harm while freeing labor" is the goal (no DEA gain expected).
EFFICIENCY_RISKS = {"stow_wip_below_band"}

ADVISORY: dict[str, str] = {
    "sort_compliance_below_target": (
        "Run a sort audit on the highest-missort aisles and re-brief temporary sorters; add a "
        "pre-pick missort sweep so uncaught missorts are recovered before routes are picked."
    ),
    "belt_gap_lost_hours": (
        "Walk the line with the most belt-gap minutes: clear jams at the loader, check carton "
        "feed and label quality; keep a water spider on the dock so the belt never starves."
    ),
    "automation_no_read_spike": (
        "Clean / re-align the automated line's scan tunnel and check label print quality; route "
        "poor-label trailers to the manual line until the no-read rate recovers."
    ),
    "container_stuck": (
        "Send the dock water spider to the stuck containers and induct them before newer ones "
        "(first-in, first-out by container)."
    ),
    "opportunity_window_closing": (
        "Decide whether to extend the sign-up window or accept the submissions now; post a new "
        "opportunity for the remaining headcount if the frame is still short."
    ),
    "scan_compliance_below_target": (
        "Inspect the induct scanner tunnel and label quality on the worst line and stage a "
        "dedicated problem-solve associate to shorten the no-read rework loop."
    ),
}

_LABELS = {
    "extend_cutoff": "Extend pick start +{a:.0f} min",
    "add_stowers": "VET {a:.0f} stowers",
    "add_pickers": "VET {a:.0f} pickers",
    "open_induct_line": "Open spare induct line",
    "priority_late_linehauls": "Prioritise late linehauls (yard + induct)",
    "move_associates": "Move {a:.0f} {from_role}→{to_role}",
    "force_induct": "Force induct {a:.0f} min after pick start",
}


class Candidate(BaseModel):
    name: str
    interventions: list[Intervention]
    labor_hours: float
    flex_needed: int = 0


def labor_hours(twin: StationOpsTwin, kind: str, amount: float) -> float:
    """Proposed cost model: *extra* paid hours. Rebalancing moves cost none."""
    stow_h = max(0.0, twin.cutoff / 60 - twin.now_minute - twin.config.labor.vet_lead_minutes) / 60
    if kind == "add_stowers":
        return amount * max(stow_h, 1.0)
    if kind == "add_pickers":
        return amount * 2.5
    return 0.0


def _label(kind: str, amount: float, params: dict) -> str:
    return _LABELS[kind].format(
        a=amount,
        from_role=params.get("from_role", "").replace("_", " "),
        to_role=params.get("to_role", "").replace("_", " "),
    )


def candidates_for(risk_type: str, twin: StationOpsTwin, *, source: str) -> list[Candidate]:
    out = []
    for spec in _C.get(risk_type, []):
        ivs = []
        for kind, amount, params in spec:
            target = params.get("to_role") if kind == "move_associates" else None
            ivs.append(
                Intervention(
                    kind=kind,
                    amount=amount,
                    at_minute=twin.now_minute,
                    target=target,
                    params=params,
                    source=source,
                )
            )
        flex = int(sum(a for k, a, _ in spec if k in ("add_stowers", "add_pickers")))
        out.append(
            Candidate(
                name=" + ".join(_label(k, a, p) for k, a, p in spec),
                interventions=ivs,
                labor_hours=round(sum(labor_hours(twin, k, a) for k, a, _ in spec), 2),
                flex_needed=flex,
            )
        )
    return out


def reflexes_for(risk, twin: StationOpsTwin, *, source: str) -> list[Intervention]:
    """Immediate, low-risk coordination actions for a risk (may be empty)."""
    now = twin.now_minute
    ev = risk.evidence
    out: list[Intervention] = []
    if risk.risk_type in ("driver_late", "wave_checkin_upcoming"):
        routes = ev.get("unnotified", [])[:40]
        if routes:
            out.append(
                Intervention(
                    kind="notify_drivers",
                    target=routes[0],
                    at_minute=now,
                    source=source,
                    params={"routes": routes},
                )
            )
    elif risk.risk_type == "driver_no_show":
        for rid in ev.get("routes", []):
            r = twin.route_by_id(rid)
            if r and twin.standby_remaining.get(r.dsp, 0) > 0:
                out.append(
                    Intervention(kind="reassign_standby", target=rid, at_minute=now, source=source)
                )
            else:
                out.append(
                    Intervention(
                        kind="move_route_wave", target=rid, amount=1, at_minute=now, source=source
                    )
                )
    elif risk.risk_type == "traffic_incident":
        out.append(
            Intervention(
                kind="notify_drivers",
                at_minute=now,
                source=source,
                params={"sector": ev.get("sector"), "leave_early_minutes": ev.get("minutes", 15)},
            )
        )
    elif risk.risk_type == "pending_swipe":
        out.append(Intervention(kind="notify_swipe_finish", at_minute=now, source=source))
    elif risk.risk_type == "routes_at_risk":
        for rid in ev.get("routes", [])[:6]:
            r = twin.route_by_id(rid)
            if r and r.priority == 0:
                out.append(
                    Intervention(kind="prioritize_route", target=rid, at_minute=now, source=source)
                )
    elif risk.risk_type == "yard_congestion" and twin.yard:
        late = [t for t in twin.yard if twin.config.linehauls[t].known_delay(now) > 0]
        pick = max(late or twin.yard, key=lambda t: twin.config.linehauls[t].volume)
        if twin.trips[pick].priority == 0:
            out.append(
                Intervention(
                    kind="resequence_unload",
                    target=twin.config.linehauls[pick].trip_id,
                    at_minute=now,
                    source=source,
                )
            )
    elif risk.risk_type == "cart_misstaged":
        for rid in ev.get("routes", []):
            out.append(Intervention(kind="restage_cart", target=rid, at_minute=now, source=source))
    elif risk.risk_type == "bag_left_in_aisle":
        for aisle in ev.get("aisles", [])[:4]:
            out.append(
                Intervention(kind="direct_sweep", target=aisle, at_minute=now, source=source)
            )
    elif risk.risk_type == "van_grounded":
        for rid in ev.get("routes", []):
            out.append(
                Intervention(
                    kind="request_replacement_van", target=rid, at_minute=now, source=source
                )
            )
    elif risk.risk_type == "vsa_queue":
        out.append(Intervention(kind="add_yard_marshal", at_minute=now, source=source))
    elif risk.risk_type == "truckfile_changed_since_plan":
        out.append(Intervention(kind="replan_next_day", at_minute=now, source=source))
    elif risk.risk_type == "next_day_staffing_gap":
        co = twin.closeout
        for rec in ev.get("recommendations", [])[:3]:
            open_same = any(
                o["status"] == "open" and o["type"] == rec["type"] and o["frame"] == rec["frame"]
                for o in co.opportunities.items
            )
            if open_same:
                continue
            out.append(
                Intervention(
                    kind="post_opportunity",
                    target=rec["type"],
                    amount=min(LEVER_LIMITS["post_opportunity"], rec["headcount"]),
                    params={"frame": rec["frame"]},
                    at_minute=now,
                    source=source,
                )
            )
    elif risk.risk_type == "finger_full_bay":
        out.append(
            Intervention(
                kind="rebalance_finger", target=ev.get("finger"), at_minute=now, source=source
            )
        )
    elif risk.risk_type == "damaged_pending_approval":
        out.append(Intervention(kind="approve_damaged", at_minute=now, source=source))
    elif risk.risk_type == "unload_sequence_conflict":
        out.append(
            Intervention(
                kind="resequence_unload", target=ev.get("trip"), at_minute=now, source=source
            )
        )
    elif risk.risk_type == "late_volume_at_pick_start" and ev.get("phase") == "after":
        out.append(Intervention(kind="change_cycle", at_minute=now, source=source))
        if twin.next_cycle_until is None:
            out.append(Intervention(kind="enable_cycle", amount=4, at_minute=now, source=source))
    elif risk.risk_type == "rotation_violation":
        out.append(Intervention(kind="rerun_rotation", at_minute=now, source=source))
    elif risk.risk_type == "network_missort_backlog":
        frm = "pick" if twin.pick_started else "stow"
        out.append(
            Intervention(
                kind="move_associates",
                target="problem_solve",
                amount=1,
                params={"from_role": frm, "to_role": "problem_solve"},
                at_minute=now,
                source=source,
            )
        )
    elif risk.risk_type == "ferry_check_due":
        out.append(Intervention(kind="check_ferry", at_minute=now, source=source))
    elif risk.risk_type == "gtdr_open":
        out.append(Intervention(kind="draft_gtdr", at_minute=now, source=source))
    elif risk.risk_type == "hv_backlog":
        frm = "pick" if twin.pick_started else "problem_solve"
        out.append(
            Intervention(
                kind="move_associates",
                target="high_value",
                amount=1,
                params={"from_role": frm, "to_role": "high_value"},
                at_minute=now,
                source=source,
            )
        )
    return out
