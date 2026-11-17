"""Canonical package status tree (HANDOFF_V2 E4).

One mapping from the twin's internal package state to the station's status
groups and sub-statuses, used by Dwell (by cycle / by delivery window),
Ageing (forward / reverse leg), RTS, and every drill-down list. Leg labels
are generic: upstream → station, station → customer, station → upstream.

Every package is in exactly one (group, sub) at any time; `classify` is a
pure function of the package and the clock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from app.simulation.station_ops.model import StationOpsTwin

FORWARD_TREE: list[tuple[str, list[str]]] = [
    ("Pending Receive", ["Manifested (upstream → station)", "In transit (upstream → station)"]),
    ("Pending Induct", ["Arrived", "Missed induct", "Marked for reprocess"]),
    ("Pending Stow", ["Inducted", "Stow buffered", "Stow problem solve", "HV pending cage scan"]),
    (
        "Pending Depart",
        [
            "Stowed (station → customer)",
            "HV in cage",
            "Picked",
            "Staged (station → customer)",
            "Pick problem solve",
        ],
    ),
    ("On Road", ["In transit (station → customer)", "Delivery failed", "Delivered"]),
    (
        "Held",
        [
            "Wrong cycle induct",
            "Next cycle (changed)",
            "Rolled over",
            "Pending approval",
            "Sidelined closed (FC return)",
            "Left in aisle",
            "Cluster transfer",
        ],
    ),
    ("Cancelled", ["Cancelled inbound"]),
]

CYCLE_COLUMNS = ("No Cycle", "CYCLE_1", "High_Value")


def classify(p, now_s: float) -> tuple[str, str]:  # noqa: C901
    s = p.status
    if s == "pending_receive":
        return ("Pending Receive", "Manifested (upstream → station)")
    if s == "cancelled_inbound":
        return ("Cancelled", "Cancelled inbound")
    if s in ("pending_induct", "inducting"):
        if p.ps_state in ("pending_reinduct", "pending_stow"):
            return ("Pending Induct", "Marked for reprocess")
        return ("Pending Induct", "Arrived")
    if s == "missed_induct":
        return ("Pending Induct", "Missed induct")
    if s == "problem_solve":
        if p.inducted_at is None and p.problem in (
            "no_read",
            "multi_read",
            "misapplied_label",
            "damaged",
            "missed_induct",
        ):
            return ("Pending Induct", "Marked for reprocess")
        return ("Pending Stow", "Stow problem solve")
    if s == "jackpot":
        return ("Pending Stow", "Stow problem solve")
    if s == "stow_buffered":
        return ("Pending Stow", "Stow buffered")
    if s in ("pending_stow", "stowing"):
        return ("Pending Stow", "Inducted")
    if s == "hv_pending_scan_in":
        return ("Pending Stow", "HV pending cage scan")
    if s == "stowed":
        return ("Pending Depart", "Stowed (station → customer)")
    if s == "hv_in_cage":
        return ("Pending Depart", "HV in cage")
    if s == "picked":
        return ("Pending Depart", "Picked")
    if s == "staged":
        return ("Pending Depart", "Staged (station → customer)")
    if s == "on_road":
        if p.attempt_at is not None and p.attempt_at <= now_s:
            return ("On Road", "Delivered" if p.delivered else "Delivery failed")
        return ("On Road", "In transit (station → customer)")
    if s == "held_wrong_cycle":
        return ("Held", "Wrong cycle induct")
    if s == "next_cycle":
        return ("Held", "Next cycle (changed)")
    if s == "rolled_over":
        return ("Held", "Rolled over")
    if s == "pending_approval":
        return ("Held", "Pending approval")
    if s == "held_damaged":
        return ("Held", "Sidelined closed (FC return)")
    if s == "left_behind":
        return ("Held", "Left in aisle")
    if s == "cluster_transfer":
        return ("Held", "Cluster transfer")
    return ("Held", "Rolled over")


def cycle_column(p) -> str:
    if p.hv:
        return "High_Value"
    if p.cycle == "UNPLANNED":
        return "No Cycle"
    return "CYCLE_1"


def delivery_window(twin: StationOpsTwin, p) -> str:
    """Scheduled delivery window from the stop's position on its route."""
    wins = twin.config.cycle.delivery_windows
    r = twin.routes[p.route]
    pos = r.packages.index(p.idx) / max(1, len(r.packages)) if r.packages else 0.0
    k = min(len(wins) - 1, int(pos * len(wins)))
    lo, hi = wins[k]
    return f"{int(lo // 60):02d}:00–{int(hi // 60):02d}:00"


def tree(twin: StationOpsTwin, *, by: str = "cycle") -> dict:
    """Dwell: counts per (group, sub) × column. `by` = cycle | window."""
    now = twin.env.now
    if by == "window":
        cols = [
            f"{int(lo // 60):02d}:00–{int(hi // 60):02d}:00"
            for lo, hi in twin.config.cycle.delivery_windows
        ]
    else:
        cols = list(CYCLE_COLUMNS)
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for p in twin.pkgs:
        g, sub = classify(p, now)
        col = delivery_window(twin, p) if by == "window" else cycle_column(p)
        row = counts.setdefault((g, sub), {c: 0 for c in cols})
        row[col] = row.get(col, 0) + 1
    groups = []
    for g, subs in FORWARD_TREE:
        rows = [
            {"status": sub, **{c: counts.get((g, sub), {}).get(c, 0) for c in cols}} for sub in subs
        ]
        total = {c: sum(r[c] for r in rows) for c in cols}
        groups.append({"group": g, **total, "rows": rows})
    return {"by": by, "columns": cols, "groups": groups, "total": len(twin.pkgs)}


def package_list(
    twin: StationOpsTwin,
    group: str,
    sub: str | None,
    column: str | None,
    by: str = "cycle",
    limit: int = 5000,
) -> list[dict]:
    now = twin.env.now
    out = []
    for p in twin.pkgs:
        g, s = classify(p, now)
        if g != group or (sub and s != sub):
            continue
        if column:
            col = delivery_window(twin, p) if by == "window" else cycle_column(p)
            if col != column:
                continue
        out.append(
            {
                "tracking_id": p.tracking_id,
                "group": g,
                "status": s,
                "cycle": cycle_column(p),
                "route": twin.routes[p.route].route_id,
                "container": twin.containers[p.container]["id"] if p.container >= 0 else None,
                "planned": p.planned,
                "location": p.location,
            }
        )
        if len(out) >= limit:
            break
    return out
