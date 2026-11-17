"""VET/VTO as opportunities with sign-up windows (HANDOFF_V2 E7, ADR-0016).

How the station actually runs it:
1. The station posts an opportunity for a time frame (a work group's window)
   with a headcount and a sign-up window.
2. Associates *submit* while the window is open. Submission is more likely
   the earlier it is posted (proposed behaviour).
3. The station *accepts* up to the headcount: first come, or rotation-aware
   (prefer associates whose acceptance helps rotation), when the window
   closes or as submissions arrive.
4. Recommendations assume no more acceptance of submitted opportunities:
   post = max(0, need − accepted) per frame.

Synthetic people only; every rate is `proposed`.
"""

from __future__ import annotations

import math

from app.simulation.station_ops.config import HEAVY_PATHS


def _clock(minute: float) -> str:
    from app.simulation.station_ops.model import clock

    return clock(minute)


class Opportunities:
    def __init__(self, closeout):
        self.co = closeout
        self.twin = closeout.twin
        self.env = closeout.env
        self.cfg = closeout.c.labor_plan
        self.items: list[dict] = []
        self._id = 0

    # --- posting ---------------------------------------------------------------

    def _frames(self) -> list[dict]:
        plan = self.co.labor_plan()
        from app.simulation.station_ops.labor_plan import frame_gaps

        return frame_gaps(plan)

    def _lead_hours(self, frame_start: float) -> float:
        return (1440 + frame_start - self.env.now / 60) / 60

    def submit_p(self, kind: str, posted: float, frame_start: float) -> float:
        lead = (1440 + frame_start - posted) / 60
        base = self.cfg.vet_submit_rate if kind == "VET" else self.cfg.vto_submit_rate
        return base * max(0.25, min(1.0, lead / 12))

    def post(self, kind: str, n: int, frame: str | None, source: str) -> str:
        kind = kind.upper()
        if kind not in ("VET", "VTO"):
            return "no-op: type must be VET or VTO"
        if self.co.started_at is None:
            return "no-op: opportunities for tomorrow are posted after dispatch"
        frames = self._frames()
        if not frames:
            return "no-op: no work-group frames"
        if frame is None:
            key = "shortfall" if kind == "VET" else "surplus"
            f = max(frames, key=lambda x: (x[key], -x["start_minute"]))
        else:
            f = next((x for x in frames if x["frame"] == frame), None)
            if f is None:
                return f"no-op: unknown frame {frame!r}"
        now = self.env.now / 60
        close = min(now + self.cfg.signup_window_minutes, 1440 + f["start_minute"] - 60)
        if close <= now:
            return "no-op: too late to open a sign-up window for that frame"
        self._id += 1
        opp = {
            "id": f"OPP-{self._id:03d}",
            "type": kind,
            "frame": f["frame"],
            "time_frame": f["window"],
            "frame_start": f["start_minute"],
            "headcount": max(1, int(n)),
            "posted_at": round(now, 2),
            "posted_clock": _clock(now),
            "window_close": round(close, 2),
            "window_close_clock": _clock(close),
            "status": "open",
            "submitted": [],
            "accepted": [],
            "source": source,
        }
        self.items.append(opp)
        self.env.process(self._run(opp))
        p = self.submit_p(kind, now, f["start_minute"])
        return (
            f"{kind} opportunity posted for {f['frame']} ({f['window']}): {opp['headcount']} HC, "
            f"sign-up window until {opp['window_close_clock']} (~{p:.0%} of eligible associates "
            "expected to submit at this lead time)"
        )

    def eligible(self, kind: str) -> list[dict]:
        taken = {s["login"] for o in self.items for s in o["submitted"]}
        if kind == "VET":
            pool = [
                p
                for p in self.co.roster
                if (p["flex"] or not p["scheduled"]) and not p["called_out"] and not p["vet"]
            ]
        else:
            pool = [
                p
                for p in self.co.roster
                if p["scheduled"] and not p["flex"] and not p["called_out"] and not p["vto"]
            ]
        return [p for p in pool if p["login"] not in taken]

    def _run(self, opp: dict):
        kind = opp["type"]
        pool = self.eligible(kind)
        p_sub = self.submit_p(kind, opp["posted_at"], opp["frame_start"])
        horizon = (opp["window_close"] - opp["posted_at"]) * 60
        arrivals = []
        for p in pool:
            u = p["u_vet"] if kind == "VET" else p["u_vto"]
            if u < p_sub:
                at = min(horizon * 0.98, p["resp"] * 60 * (0.3 + u))
                arrivals.append((at, p))
        arrivals.sort(key=lambda x: x[0])
        elapsed = 0.0
        for at, p in arrivals:
            if opp["status"] != "open":
                break
            if at > elapsed:
                yield self.env.timeout(at - elapsed)
                elapsed = at
            if opp["status"] != "open":
                break
            opp["submitted"].append({"login": p["login"], "clock": _clock(self.env.now / 60)})
            if self.cfg.acceptance_rule == "first_come" and len(opp["accepted"]) < opp["headcount"]:
                self._accept(opp, p)
        if opp["status"] == "open":
            remaining = opp["window_close"] * 60 - self.env.now
            if remaining > 0:
                yield self.env.timeout(remaining)
            self._close(opp, "window closed")

    def _rank(self, opp: dict, p: dict) -> float:
        hist = p.get("history_paths") or []
        heavy = sum(1 for x in hist if x in HEAVY_PATHS)
        if opp["type"] == "VTO":
            return -heavy - p["skill"] * 0.1  # release those carrying the heaviest load
        return -p["skill"] - (0.3 if not hist else 0.0)

    def _accept(self, opp: dict, p: dict) -> None:
        if any(a["login"] == p["login"] for a in opp["accepted"]):
            return
        opp["accepted"].append({"login": p["login"], "clock": _clock(self.env.now / 60)})
        if opp["type"] == "VET":
            p["vet"] = True
        else:
            p["vto"] = True

    def _close(self, opp: dict, why: str) -> None:
        if opp["status"] != "open":
            return
        if self.cfg.acceptance_rule == "rotation_aware":
            subs = [
                next(x for x in self.co.roster if x["login"] == s["login"])
                for s in opp["submitted"]
            ]
            for p in sorted(subs, key=lambda q: self._rank(opp, q)):
                if len(opp["accepted"]) >= opp["headcount"]:
                    break
                self._accept(opp, p)
        opp["status"] = "closed"
        opp["closed_clock"] = _clock(self.env.now / 60)
        opp["closed_reason"] = why

    def close(self, opp_id: str | None, source: str) -> str:
        opens = [o for o in self.items if o["status"] == "open"]
        if opp_id:
            opens = [o for o in opens if o["id"] == opp_id]
        if not opens:
            return "no-op: no open sign-up window"
        for o in opens:
            self._close(o, f"closed early by {source}")
        acc = sum(len(o["accepted"]) for o in opens)
        return f"{len(opens)} sign-up window(s) closed; {acc} associate(s) accepted"

    # --- reading -------------------------------------------------------------------

    def accepted(self, kind: str, frame: str | None = None) -> int:
        return sum(
            len(o["accepted"])
            for o in self.items
            if o["type"] == kind and (frame is None or o["frame"] == frame)
        )

    def recommendations(self) -> list[dict]:
        """How many more to post per frame, assuming no more acceptance of
        submitted opportunities."""
        out = []
        for f in self._frames():
            vet = math.ceil(f["shortfall"] - 0.25) - self.accepted("VET", f["frame"])
            vto = math.floor(f["surplus"] - 0.5) - self.accepted("VTO", f["frame"])
            if vet > 0:
                out.append(
                    {
                        "type": "VET",
                        "frame": f["frame"],
                        "time_frame": f["window"],
                        "headcount": vet,
                    }
                )
            if vto > 0:
                out.append(
                    {
                        "type": "VTO",
                        "frame": f["frame"],
                        "time_frame": f["window"],
                        "headcount": vto,
                    }
                )
        return out

    def view(self) -> dict:
        return {
            "opportunities": [
                {
                    **{k: v for k, v in o.items() if k not in ("submitted", "accepted")},
                    "window": "Open" if o["status"] == "open" else "Closed",
                    "submitted": len(o["submitted"]),
                    "accepted": len(o["accepted"]),
                    "submissions": o["submitted"][-20:],
                }
                for o in self.items
            ],
            "recommendations": self.recommendations() if self.co.started_at is not None else [],
            "rule": self.cfg.acceptance_rule,
            "signup_window_minutes": self.cfg.signup_window_minutes,
        }
