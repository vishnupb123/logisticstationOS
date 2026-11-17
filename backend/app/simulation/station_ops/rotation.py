"""Shift rotation engine (HANDOFF_V2 E8, ADR-0016).

Per associate: trained paths, path history (last 3 days), *disallowed*
paths (a heavy path on >= N of the last 3 days; proposed rule, Q10), a
rotation priority (None / Low / High) and a recommended path.

Assignment is a min-cost matching of associates to path slots:
    cost = −skill  + repetition penalty (same path as yesterday)
           − priority bonus (rotating a High-priority associate off heavy work)
           + ∞ for untrained or disallowed paths.
Uses scipy's Hungarian solver when scipy is installed, else a greedy pass
with the same costs. Deterministic for a given roster.
"""

from __future__ import annotations

from app.simulation.station_ops.config import HEAVY_PATHS, PROCESS_PATHS

BIG = 1e6

#: path → the twin role that staffs it (for the next day's config)
PATH_ROLE = {
    "auto_induct_loader": "induct",
    "induct": "induct",
    "stow": "stow",
    "sort_problem_solve": "problem_solve",
    "high_value": "high_value",
    "pick": "pick",
}


def disallowed_paths(history: list[str], n_days: int) -> list[str]:
    last3 = history[-3:]
    return sorted({p for p in last3 if p in HEAVY_PATHS and last3.count(p) >= n_days})


def rotation_priority(history: list[str]) -> str:
    last3 = history[-3:]
    if not last3:
        return "None"
    if len(last3) == 3 and (len(set(last3)) == 1 or all(p in HEAVY_PATHS for p in last3)):
        return "High"
    if max(last3.count(p) for p in set(last3)) >= 2:
        return "Low"
    return "None"


def cost(p: dict, path: str, n_days: int) -> float:
    hist = p.get("history_paths") or []
    if path not in p.get("trained_paths", []):
        return BIG
    if path in disallowed_paths(hist, n_days):
        return BIG
    c = -p["skill"]
    if hist and hist[-1] == path:
        c += 1.0
    if rotation_priority(hist) == "High" and path not in HEAVY_PATHS:
        c -= 0.6
    return c


def assign(
    people: list[dict], slots: list[tuple[str, str]], n_days: int, max_consecutive: int = 2
) -> tuple[list[dict], dict]:
    """slots: [(path, where)]. Returns assignments and stats."""
    m, k = len(people), len(slots)
    matrix = [[cost(p, path, n_days) for path, _ in slots] for p in people]
    pairs: list[tuple[int, int]] = []
    try:
        from scipy.optimize import linear_sum_assignment  # type: ignore

        if m and k:
            rows, cols = linear_sum_assignment(matrix)
            pairs = [(int(r), int(c)) for r, c in zip(rows, cols, strict=True)]
        solver = "hungarian"
    except Exception:  # pragma: no cover - scipy missing
        solver = "greedy"
        used: set[int] = set()
        order = sorted(range(k), key=lambda j: min((matrix[i][j] for i in range(m)), default=BIG))
        for j in order:
            best = min(
                (i for i in range(m) if i not in used), key=lambda i: matrix[i][j], default=None
            )
            if best is not None:
                used.add(best)
                pairs.append((best, j))
    by_slot = {j: i for i, j in pairs}
    out, violations, unfilled = [], 0, 0
    for j, (path, where) in enumerate(slots):
        i = by_slot.get(j)
        if i is None or matrix[i][j] >= BIG:
            unfilled += 1
            out.append(
                {
                    "path": path,
                    "role": PATH_ROLE.get(path, "support"),
                    "where": where,
                    "login": None,
                    "ok": False,
                    "note": "unfilled (no trained, allowed associate)",
                }
            )
            continue
        p = people[i]
        hist = p.get("history_paths") or []
        streak = 0
        for x in reversed(hist):
            if x != path:
                break
            streak += 1
        ok = streak < max_consecutive  # one more day on the same path would break rotation
        violations += 0 if ok else 1
        out.append(
            {
                "path": path,
                "path_label": PROCESS_PATHS[path]["label"],
                "role": PATH_ROLE.get(path, "support"),
                "where": where,
                "login": p["login"],
                "ok": ok,
                "vet": p.get("vet", False),
                "history": hist,
                "note": "" if ok else f"{streak} days in a row on {path}",
            }
        )
    filled = k - unfilled
    return out, {
        "solver": solver,
        "slots": k,
        "filled": filled,
        "unfilled": unfilled,
        "violations": violations,
        "compliance": round(1 - violations / max(1, filled), 3),
    }


def table(people: list[dict], assignments: list[dict], n_days: int) -> list[dict]:
    rec = {a["login"]: a["path"] for a in assignments if a["login"]}
    rows = []
    for p in people:
        hist = p.get("history_paths") or []
        rows.append(
            {
                "login": p["login"],
                "rotation_priority": rotation_priority(hist),
                "disallowed_paths": disallowed_paths(hist, n_days),
                "trained_paths": p.get("trained_paths", []),
                "history": hist,
                "recommended_path": rec.get(p["login"]),
                "flex": p.get("flex", False),
                "vet": p.get("vet", False),
                "vto": p.get("vto", False),
                "called_out": p.get("called_out", False),
            }
        )
    order = {"High": 0, "Low": 1, "None": 2}
    rows.sort(key=lambda r: (order[r["rotation_priority"]], r["login"]))
    return rows
