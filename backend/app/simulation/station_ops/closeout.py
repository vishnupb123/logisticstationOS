"""After dispatch: close the day and plan tomorrow.

Once every route has departed, associates finish their shift (sweepers
finish their aisles first). The floor is left to a supervisor and a manager:

Supervisor (works a priority queue of tasks, one at a time):
- GTDR (Global Trailer Dock and Release) records for irregular trailers:
  late inbound trucks and outbound pallet trucks (the field set is a
  proposed, generic one);
- ferry status checks for tomorrow's ferry-borne trips, every 30 min until
  the final truckfile, then hourly — revisions keep coming *after* the final
  truckfile, and a ferry revision is only learned when someone checks;
- publishing the final truckfile;
- in-station scrub (finds what the sweep missed → cluster transfer; resolves
  missing packages) and on-road scrub (reconciles returns) before next shift.

Manager:
- headcount & volume plan: predicted OFD volume, SPR, TPH, needed vs
  expected headcount → VET / VTO offers (associates *choose* whether to
  accept; later offers get fewer takers);
- tomorrow's daily plan: volume divided across aisles, stow zones, and task
  assignment that satisfies the job-rotation rule;
- a final review at end of shift that re-plans if anything changed.

Sudden changes (seeded, unknown in advance): a late network trailer, a
delayed outbound pallet truck, ferry delays / a cancelled sailing / extra
volume after the final truckfile, associates calling out for tomorrow. The
Shift Planning agent (app/agents/station_ops) can react to each as it
happens — re-check a ferry, re-plan, top up VET early, pre-draft GTDRs —
instead of waiting for the default checkpoints.

Synthetic throughout; every rate and timing is a configurable assumption.
Nothing here contacts a real ferry operator, associate or carrier.
"""

import math
import random
from collections import Counter
from datetime import timedelta

from app.simulation.station_ops import labor_plan as lp
from app.simulation.station_ops import rotation as rot
from app.simulation.station_ops.config import PROCESS_PATHS
from app.simulation.station_ops.opportunities import Opportunities
from app.simulation.station_ops.plan import generate_linehaul_plan

TOMORROW_SHIFT_START = 1440 + 150  # 02:30 next day (site profile), from today's midnight
SORT_PATHS = (
    "auto_induct_loader",
    "labeler",
    "container_building",
    "induct",
    "non_con_handling",
    "sort_problem_solve",
    "stow",
)


def _clock(minute: float) -> str:
    m = int(round(minute))
    day, m = divmod(m, 1440)
    label = f"{m // 60:02d}:{m % 60:02d}"
    return label if day == 0 else f"{label}+{day}d"


class Closeout:
    def __init__(self, twin):
        self.twin = twin
        self.c = twin.config
        self.cfg = twin.config.closeout
        self.env = twin.env
        self.started_at: float | None = None
        self.complete = False
        self.done_event = self.env.event()
        self.tasks: list[dict] = []
        self.gtdr: list[dict] = []
        self.ferry_checks: list[dict] = []
        self.truckfile_log: list[dict] = []
        self.truckfile_version = 0  # 0 = draft; 1 = final; >1 = revised after final
        self.final_published_at: float | None = None
        self.plan: dict | None = None
        self.plan_history: list[dict] = []
        self.callouts: list[dict] = []
        self.scrubs: dict[str, dict] = {}
        self.drafted_gtdr = False
        self.headcount: dict | None = None
        self.readiness: dict | None = None
        self.finished_at: float | None = None
        self._tid = 0
        self._gid = 0
        self._rng = random.Random(f"closeout:{self.c.seed}")
        self._build_tomorrow()
        self._build_people()
        self.opportunities = Opportunities(self)
        self.rotation: list[dict] = []
        self.rotation_stats: dict = {}
        self.rotation_runs = 0

    # --- tomorrow's truth (unknown until revealed) ----------------------------------

    def _build_tomorrow(self) -> None:
        rng = random.Random(f"tomorrow:{self.c.seed}")
        self.tomorrow = self.c.ofd_date + timedelta(days=1)
        volume = int(max(6000, self.c.planned_volume) * rng.uniform(0.9, 1.12))
        trips = generate_linehaul_plan(self.c.seed * 31 + 7, self.tomorrow, total_volume=volume)
        self.trips: list[dict] = []
        for t in trips:
            self.trips.append(
                {
                    "trip_id": t.trip_id,
                    "origin": t.origin,
                    "via_ferry": t.via_ferry,
                    "sailing": t.ferry_sailing,
                    "planned_arrival": t.planned_arrival_minute,
                    "planned_volume": t.volume,
                    # what the station currently believes
                    "known_delay": 0.0,
                    "known_volume": t.volume,
                    "known_cancelled": False,
                    "added": False,
                    "last_checked": None,
                }
            )
        # revisions: (reveal_minute, trip index, field, value, needs_ferry_check, why)
        self.revisions: list[dict] = []
        start = 11 * 60
        for i, t in enumerate(self.trips):
            if t["via_ferry"] and rng.random() < 0.35:
                self.revisions.append(
                    {
                        "at": rng.uniform(start, 1260),
                        "trip": i,
                        "field": "known_delay",
                        "value": round(rng.uniform(20, 200)),
                        "check": True,
                        "why": rng.choice(
                            ("sailing delayed (weather)", "port congestion", "vessel swap")
                        ),
                    }
                )
            elif not t["via_ferry"] and rng.random() < 0.12:
                self.revisions.append(
                    {
                        "at": rng.uniform(start, 1260),
                        "trip": i,
                        "field": "known_volume",
                        "value": max(50, round(t["planned_volume"] * rng.uniform(0.75, 1.3))),
                        "check": False,
                        "why": "network volume re-forecast",
                    }
                )
        # one sudden change after the final truckfile, most days
        if rng.random() < 0.65:
            at = rng.uniform(self.cfg.final_truckfile_minute + 30, 1275)
            kind = rng.choice(("cancel_sailing", "big_delay", "extra_trailer"))
            ferries = [i for i, t in enumerate(self.trips) if t["via_ferry"]]
            if kind == "cancel_sailing" and ferries:
                self.revisions.append(
                    {
                        "at": at,
                        "trip": rng.choice(ferries),
                        "field": "known_cancelled",
                        "value": True,
                        "check": True,
                        "why": "sailing cancelled after final truckfile",
                    }
                )
            elif kind == "big_delay" and ferries:
                self.revisions.append(
                    {
                        "at": at,
                        "trip": rng.choice(ferries),
                        "field": "known_delay",
                        "value": round(rng.uniform(240, 420)),
                        "check": True,
                        "why": "ferry breakdown — next sailing",
                    }
                )
            else:
                self.trips.append(
                    {
                        "trip_id": f"LH-X{rng.randrange(100, 999)}",
                        "origin": "XDOCK-W1",
                        "via_ferry": False,
                        "sailing": None,
                        "planned_arrival": rng.choice((200, 230, 260)),
                        "planned_volume": 0,
                        "known_delay": 0.0,
                        "known_volume": 0,
                        "known_cancelled": False,
                        "added": True,
                        "last_checked": None,
                    }
                )
                self.revisions.append(
                    {
                        "at": at,
                        "trip": len(self.trips) - 1,
                        "field": "known_volume",
                        "value": rng.randrange(600, 1400),
                        "check": False,
                        "why": "extra trailer added by the network after final truckfile",
                    }
                )
        self.revisions.sort(key=lambda r: r["at"])
        for r in self.revisions:
            r["revealed"] = False
        # sudden events during close-out
        self.late_trailer = (
            {"at": rng.uniform(start + 30, 960), "units": rng.randrange(150, 600)}
            if rng.random() < 0.45
            else None
        )
        self.pallet_delay = rng.uniform(15, 60) if rng.random() < 0.3 else 0.0

    def _build_people(self) -> None:
        rng = random.Random(f"roster:{self.c.seed}")
        roles = ("induct", "stow", "pick", "problem_solve", "high_value")
        weights = (2, 10, 4, 2, 2)
        prng = random.Random(f"paths:{self.c.seed}")
        all_paths = [*SORT_PATHS, "pick", "high_value"]
        path_w = (2, 2, 3, 2, 1, 2, 10, 4, 1)
        role_of = {
            "auto_induct_loader": "induct",
            "labeler": "induct",
            "container_building": "stow",
            "induct": "induct",
            "non_con_handling": "stow",
            "sort_problem_solve": "problem_solve",
            "stow": "stow",
            "pick": "pick",
            "high_value": "high_value",
        }
        self.roster: list[dict] = []
        for i in range(self.cfg.roster_size):
            hist = rng.choices(roles, weights=weights, k=3)
            if rng.random() < 0.4:  # some associates are stuck in one role
                hist = [hist[0]] * 3
            hp = prng.choices(all_paths, weights=path_w, k=3)
            if prng.random() < 0.35:
                hp = [hp[0]] * 3
            trained = set(hp) | set(prng.sample(all_paths, prng.randint(2, 5))) | {"pick"}
            self.roster.append(
                {
                    "login": f"assoc{rng.randrange(100, 999)}{chr(97 + i % 26)}",
                    "skill": round(max(0.6, rng.lognormvariate(0, 0.15)), 2),
                    "history_paths": hp,
                    "trained_paths": sorted(trained),
                    "history": [role_of[x] for x in hp],  # oldest → yesterday... → today
                    "scheduled": rng.random() > 0.12,
                    "u_vet": rng.random(),
                    "u_vto": rng.random(),
                    "resp": rng.lognormvariate(math.log(self.cfg.vet_response_mean_minutes), 0.5),
                    "called_out": False,
                    "vto": False,
                    "vet": False,
                    "flex": False,
                }
            )
        for k in range(self.cfg.vet_pool):
            self.roster.append(
                {
                    "login": f"flex{rng.randrange(100, 999)}{chr(97 + k % 26)}",
                    "skill": round(max(0.6, rng.lognormvariate(-0.05, 0.15)), 2),
                    "history_paths": [],
                    "trained_paths": sorted({"stow", "pick", *prng.sample(all_paths, 2)}),
                    "history": [],
                    "scheduled": False,
                    "u_vet": rng.random(),
                    "u_vto": 1.0,
                    "resp": rng.lognormvariate(math.log(self.cfg.vet_response_mean_minutes), 0.5),
                    "called_out": False,
                    "vto": False,
                    "vet": False,
                    "flex": True,
                }
            )
        scheduled = [p for p in self.roster if p["scheduled"]]
        n_call = rng.choice((0, 1, 1, 2, 2, 3, 4))
        self._callout_plan = [
            (rng.uniform(960, 1320), p["login"]) for p in rng.sample(scheduled, n_call)
        ]

    # --- task queue -------------------------------------------------------------

    def task(self, owner: str, kind: str, title: str, minutes: float, priority: int, **data):
        self._tid += 1
        t = {
            "id": self._tid,
            "owner": owner,
            "kind": kind,
            "title": title,
            "minutes": minutes,
            "priority": priority,
            "status": "queued",
            "created": self.env.now / 60,
            "created_clock": _clock(self.env.now / 60),
            "started": None,
            "finished": None,
            "result": None,
            **data,
        }
        self.tasks.append(t)
        t["work_item"] = self.twin.work_items.add(
            kind=kind,
            title=title,
            owner=owner,
            started_by="system",
            ref=str(self._tid),
            source_ref={"closeout_task": self._tid},
        )["id"]
        return t

    def _has(self, owner: str, kind: str) -> bool:
        return any(
            t["owner"] == owner and t["kind"] == kind and t["status"] in ("queued", "in_progress")
            for t in self.tasks
        )

    def _worker(self, owner: str, end: float):
        while True:
            queued = [t for t in self.tasks if t["owner"] == owner and t["status"] == "queued"]
            now = self.env.now / 60
            if not queued:
                if now >= end and not self._pending_for(owner):
                    return
                yield self.env.timeout(60)
                continue
            t = min(queued, key=lambda x: (x["priority"], x["created"], x["id"]))
            t["status"], t["started"] = "in_progress", now
            minutes = t["minutes"]
            if t["kind"] == "gtdr" and self.drafted_gtdr:
                minutes = self.cfg.gtdr_drafted_minutes
            yield self.env.timeout(minutes * 60)
            t["result"] = self._do(t)
            t["status"], t["finished"] = "done", self.env.now / 60
            wi = self.twin.work_items.by_id(t.get("work_item", ""))
            if wi:
                self.twin.work_items.resolve_item(wi, t["result"] or "done")
            t["finished_clock"] = _clock(self.env.now / 60)

    def _pending_for(self, owner: str) -> bool:
        return any(t["owner"] == owner and t["status"] != "done" for t in self.tasks)

    # --- the close-out day -------------------------------------------------------

    def run(self):
        tw = self.twin
        self.started_at = self.env.now / 60
        tw.notify(
            "supervisor",
            "closeout",
            "info",
            "Departures complete — close-out started",
            "Associates are off shift. Supervisor: GTDRs, ferry checks, truckfile, scrubs. "
            "Manager: headcount, VET/VTO, tomorrow's plan.",
        )
        self.task("supervisor", "floor_close", "Floor close: confirm sweep, carts and cages", 8, 2)
        for i, plan in enumerate(self.c.linehauls):
            trip = tw.trips[i]
            if trip.arrived_at is not None and trip.arrived_at > tw.cutoff:
                self._new_gtdr(
                    "inbound_late",
                    plan.trip_id,
                    plan.origin,
                    plan.planned_arrival_minute,
                    trip.arrived_at / 60,
                    plan.volume,
                    plan.delay_reason or ("ferry delay" if plan.via_ferry else "late linehaul"),
                    door=trip.door,
                )
        procs = (
            self._worker("supervisor", self.cfg.supervisor_end_minute),
            self._worker("manager", self.cfg.supervisor_end_minute),
            self._ferry_schedule(),
            self._revision_feed(),
            self._inbound_watch(),
            self._pallet_truck(),
            self._scrub_schedule(),
            self._manager_schedule(),
            self._callout_feed(),
        )
        handles = [self.env.process(p) for p in procs]
        yield handles[0] & handles[1]
        self._finish()

    def _finish(self) -> None:
        self.complete = True
        self.finished_at = self.env.now / 60
        self.readiness = self.evaluate()
        self.twin.log(
            "closeout",
            f"Close-out complete; plan v{self.plan['version'] if self.plan else 0} "
            f"on truckfile v{self.truckfile_version}",
        )
        if not self.done_event.triggered:
            self.done_event.succeed()

    # --- inbound / outbound trailers → GTDR -------------------------------------------

    def _new_gtdr(self, direction, trailer, place, scheduled, actual, units, reason, door=None):
        self._gid += 1
        g = {
            "gtdr_id": f"GTDR-{self._gid:04d}",
            "direction": direction,
            "trailer": trailer,
            "place": place,
            "scheduled": _clock(scheduled),
            "actual": _clock(actual),
            "delay_minutes": round(max(0.0, actual - scheduled)),
            "door": door,
            "units": units,
            "pallets": max(1, math.ceil(units / 60)),
            "reason": reason,
            "seal": f"SEAL-{self._rng.randrange(10000, 99999)}",
            "status": "drafted" if self.drafted_gtdr else "open",
            "opened": self.env.now / 60,
            "opened_clock": _clock(self.env.now / 60),
            "filed_clock": None,
        }
        self.gtdr.append(g)
        self.task(
            "supervisor",
            "gtdr",
            f"File {g['gtdr_id']} ({trailer})",
            self.cfg.gtdr_minutes,
            1,
            gtdr_id=g["gtdr_id"],
        )
        self.twin.notify(
            "supervisor",
            "gtdr",
            "warning",
            f"GTDR needed — {trailer}",
            f"{'Late inbound' if direction == 'inbound_late' else 'Outbound pallet'} trailer "
            f"{trailer} ({place}), scheduled {g['scheduled']}, actual {g['actual']} "
            f"(+{g['delay_minutes']} min): {reason}.",
            gtdr_id=g["gtdr_id"],
        )
        return g

    def _inbound_watch(self):
        tw = self.twin
        seen = {i for i, t in enumerate(tw.trips) if t.arrived_at is not None}
        while self.env.now / 60 < self.cfg.supervisor_end_minute - 30:
            for i, trip in enumerate(tw.trips):
                if i not in seen and trip.status in ("in_yard", "unloading", "arrived"):
                    seen.add(i)
                    plan = self.c.linehauls[i]
                    self._new_gtdr(
                        "inbound_late",
                        plan.trip_id,
                        plan.origin,
                        plan.planned_arrival_minute,
                        self.env.now / 60,
                        plan.volume,
                        plan.delay_reason or "late linehaul",
                    )
            lt = self.late_trailer
            if lt and not lt.get("arrived") and self.env.now / 60 >= lt["at"]:
                lt["arrived"] = True
                tw.counters["late_trailer_units"] += lt["units"]
                tw.log("inbound", f"Unplanned late trailer arrived with {lt['units']} units")
                self._new_gtdr(
                    "inbound_late",
                    f"LH-L{self._rng.randrange(100, 999)}",
                    "HUB-N2",
                    lt["at"] - self._rng.uniform(240, 480),
                    lt["at"],
                    lt["units"],
                    "unplanned late network trailer — volume rolls to next cycle",
                )
            yield self.env.timeout(5 * 60)

    def _pallet_truck(self):
        tw = self.twin
        sched = self.started_at + self.cfg.outbound_pallet_truck_after_minutes
        yield self.env.timeout(max(0.0, (sched + self.pallet_delay) * 60 - self.env.now))
        held = sum(1 for p in tw.pkgs if p.status == "held_damaged")
        units = held + len([b for b in tw.backlog if b["status"] == "retained"]) // 3 + 40
        tw.log("outbound", f"Outbound pallet truck departed ({units} units)")
        if self.pallet_delay:
            self._new_gtdr(
                "outbound_pallet",
                f"PT-{self._rng.randrange(100, 999)}",
                "RETURNS-HUB",
                sched,
                self.env.now / 60,
                units,
                "carrier late for outbound pallet collection",
            )
        else:
            self._gid += 1
            self.gtdr.append(
                {
                    "gtdr_id": f"GTDR-{self._gid:04d}",
                    "direction": "outbound_pallet",
                    "trailer": f"PT-{self._rng.randrange(100, 999)}",
                    "place": "RETURNS-HUB",
                    "scheduled": _clock(sched),
                    "actual": _clock(self.env.now / 60),
                    "delay_minutes": 0,
                    "door": None,
                    "units": units,
                    "pallets": max(1, math.ceil(units / 60)),
                    "reason": "on time",
                    "seal": f"SEAL-{self._rng.randrange(10000, 99999)}",
                    "status": "filed",
                    "opened": self.env.now / 60,
                    "opened_clock": _clock(self.env.now / 60),
                    "filed_clock": _clock(self.env.now / 60),
                }
            )

    def draft_gtdrs(self, source: str) -> str:
        self.drafted_gtdr = True
        n = 0
        for g in self.gtdr:
            if g["status"] == "open":
                g["status"] = "drafted"
                n += 1
        return (
            f"{n} GTDR(s) pre-drafted from trailer, door and timing data — supervisor only "
            "verifies and signs; future GTDRs drafted automatically"
        )

    # --- truckfile ------------------------------------------------------------------

    def _ferry_schedule(self):
        while self.env.now / 60 < self.cfg.supervisor_end_minute - 30:
            final = self.final_published_at is not None
            if not self._has("supervisor", "ferry_check"):
                self.task(
                    "supervisor",
                    "ferry_check",
                    "Check ferry statuses for tomorrow",
                    self.cfg.ferry_check_minutes,
                    2,
                )
            if (
                not final
                and self.env.now / 60 >= self.cfg.final_truckfile_minute - 15
                and not self._has("supervisor", "publish_truckfile")
            ):
                self.task("supervisor", "publish_truckfile", "Publish final truckfile", 10, 1)
            step = (
                self.cfg.ferry_check_minutes_after_final
                if final
                else self.cfg.ferry_check_minutes_before_final
            )
            yield self.env.timeout(step * 60)

    def request_ferry_check(self, source: str) -> str:
        if self.started_at is None:
            return "no-op: close-out has not started"
        if self._has("supervisor", "ferry_check"):
            for t in self.tasks:
                if t["kind"] == "ferry_check" and t["status"] == "queued":
                    t["priority"] = 0
            return "ferry check moved to the top of the supervisor's queue"
        self.task(
            "supervisor",
            "ferry_check",
            f"Ferry check requested ({source})",
            self.cfg.ferry_check_minutes,
            0,
        )
        return "ferry check queued at top priority"

    def _revision_feed(self):
        """Pushed revisions (network re-forecasts, extra trailers) arrive by
        themselves; ferry revisions wait for someone to check."""
        while self.env.now / 60 < self.cfg.supervisor_end_minute:
            now = self.env.now / 60
            for r in self.revisions:
                if not r["revealed"] and not r["check"] and r["at"] <= now:
                    self._reveal(r, "network update")
            yield self.env.timeout(5 * 60)

    def _reveal(self, r: dict, how: str) -> None:
        t = self.trips[r["trip"]]
        before = t[r["field"]]
        t[r["field"]] = r["value"]
        r["revealed"], r["revealed_at"] = True, self.env.now / 60
        after_final = self.final_published_at is not None
        if after_final:
            self.truckfile_version += 1
        self.truckfile_log.append(
            {
                "clock": _clock(self.env.now / 60),
                "trip_id": t["trip_id"],
                "field": r["field"].replace("known_", ""),
                "before": before,
                "after": r["value"],
                "why": r["why"],
                "how": how,
                "after_final": after_final,
                "version": self.truckfile_version,
            }
        )
        sev = "critical" if after_final else "info"
        self.twin.notify(
            "manager" if after_final else "supervisor",
            "truckfile_revision",
            sev,
            f"Truckfile {'revised after final' if after_final else 'update'} — {t['trip_id']}",
            f"{t['trip_id']} ({t['origin']}): {r['field'].replace('known_', '')} "
            f"{before} → {r['value']} ({r['why']}; learned via {how}).",
            trip_id=t["trip_id"],
        )

    def ferry_check(self) -> str:
        now = self.env.now / 60
        found = 0
        for r in self.revisions:
            if r["check"] and not r["revealed"] and r["at"] <= now:
                self._reveal(r, "ferry status check")
                found += 1
        for t in self.trips:
            if t["via_ferry"]:
                t["last_checked"] = _clock(now)
        self.ferry_checks.append({"clock": _clock(now), "changes": found})
        return f"{found} change(s) found" if found else "no changes"

    # --- scrubs ---------------------------------------------------------------------------

    def _scrub_schedule(self):
        tw = self.twin
        while tw._sweep_open() and self.env.now / 60 < self.started_at + 90:
            yield self.env.timeout(5 * 60)
        self.task(
            "supervisor",
            "in_station_scrub",
            "In-station scrub (walk the floor)",
            self.cfg.in_station_scrub_minutes,
            3,
        )
        while self.env.now / 60 < 20 * 60:
            returned = all(
                d.return_at is not None and d.return_at <= self.env.now
                for d in tw.drivers
                if d.departed_at is not None
            )
            if returned:
                break
            yield self.env.timeout(10 * 60)
        self.task(
            "supervisor",
            "on_road_scrub",
            "On-road scrub (reconcile returns)",
            self.cfg.on_road_scrub_minutes,
            3,
        )

    def _in_station_scrub(self) -> str:
        tw = self.twin
        found = 0
        for p in tw.pkgs:
            if p.status == "left_behind":
                if random.Random(f"scrub:{self.c.seed}:{p.idx}").random() < 0.9:
                    p.status, p.recovered, p.location = "cluster_transfer", "scrub", "CT"
                    found += 1
        tw.counters["cluster_transfer"] += found
        rec = tw.apply(_iv("start_scrub", target="in_station", source="supervisor_closeout"))
        self.scrubs["in_station"] = {
            "clock": _clock(self.env.now / 60),
            "left_behind_found": found,
            "backlog": rec["effect"],
        }
        return f"{found} left-behind package(s) → cluster transfer; {rec['effect']}"

    def _on_road_scrub(self) -> str:
        tw = self.twin
        now = self.env.now
        rts = sum(
            1
            for p in tw.pkgs
            if p.departed_at is not None
            and (p.attempted is False or (p.attempt_at and p.attempt_at <= now and not p.delivered))
        )
        rec = tw.apply(_iv("start_scrub", target="on_road", source="supervisor_closeout"))
        unswiped = sum(1 for d in tw.drivers if d.return_at and d.swiped_at is None)
        self.scrubs["on_road"] = {
            "clock": _clock(now / 60),
            "returned_to_station": rts,
            "unswiped_drivers": unswiped,
            "backlog": rec["effect"],
        }
        return f"{rts} undelivered package(s) reconciled for re-attempt; {rec['effect']}"

    # --- manager: headcount, VET/VTO, plan ---------------------------------------------

    def _manager_schedule(self):
        while self.final_published_at is None:
            yield self.env.timeout(5 * 60)
        yield self.env.timeout(20 * 60)
        self.task("manager", "headcount", "Headcount & volume plan → VET/VTO offers", 20, 1)
        yield self.env.timeout(max(0.0, self.cfg.build_plan_minute * 60 - self.env.now))
        self.task("manager", "build_plan", "Build tomorrow's plan (aisles, tasks, rotation)", 30, 1)
        yield self.env.timeout(max(0.0, self.cfg.manager_review_minute * 60 - self.env.now))
        self.task("manager", "final_review", "End-of-shift review of the plan", 15, 1)

    def _callout_feed(self):
        for at, login in sorted(self._callout_plan):
            if at * 60 > self.env.now:
                yield self.env.timeout(at * 60 - self.env.now)
            p = next(x for x in self.roster if x["login"] == login)
            p["called_out"] = True
            self.callouts.append({"clock": _clock(self.env.now / 60), "login": login})
            self.twin.notify(
                "manager",
                "callout",
                "warning",
                f"{login} called out for tomorrow",
                f"{login} won't be in tomorrow — expected headcount down by one.",
            )

    def request_replan(self, source: str) -> str:
        if self.final_published_at is None:
            return "no-op: no final truckfile yet — nothing to plan from"
        if self._has("manager", "replan"):
            return "no-op: re-plan already queued"
        self.task("manager", "replan", f"Re-plan tomorrow ({source})", 10, 0)
        return "manager re-plan queued at top priority (needs, VET/VTO top-up, assignments)"

    def known_ofd(self) -> dict:
        """Tomorrow's OFD volume as currently known: trips expected before
        tomorrow's pick start + today's carry-over (rollover, cluster transfer,
        re-attempts, late trailer)."""
        tw = self.twin
        pick = self.c.cycle.pick_start_minute
        in_time = at_risk = cancelled = 0
        for t in self.trips:
            if t["known_cancelled"]:
                cancelled += t["known_volume"]
                continue
            eta = t["planned_arrival"] + t["known_delay"]
            if eta <= pick - 60:
                in_time += t["known_volume"]
            else:
                at_risk += t["known_volume"]
        now = self.env.now
        st = Counter(p.status for p in tw.pkgs)
        reattempt = sum(
            1
            for p in tw.pkgs
            if p.departed_at is not None
            and (p.attempted is False or (p.attempt_at and p.attempt_at <= now and not p.delivered))
        )
        carry = (
            st["rolled_over"]
            + st["cluster_transfer"]
            + st["left_behind"]
            + reattempt
            + tw.counters["late_trailer_units"]
        )
        return {
            "linehaul_in_time": in_time,
            "linehaul_at_risk": at_risk,
            "cancelled": cancelled,
            "carryover": carry,
            "rollover": st["rolled_over"],
            "cluster_transfer": st["cluster_transfer"],
            "reattempt": reattempt,
            "late_trailer": tw.counters["late_trailer_units"],
            "ofd_volume": in_time + carry,
        }

    def needs(self, ofd: int) -> dict:
        ind, stow = self.c.induct, self.c.stow
        lab = self.c.labor
        routes = max(40, min(120, math.ceil(ofd / self.cfg.target_spr)))
        tph = ofd / self.cfg.induct_window_hours
        buf = self.cfg.planning_buffer
        inductors = max(1, math.ceil(tph / ind.rate_pph_per_line))
        stowers = max(1, math.ceil(tph * buf / stow.rate_pph_per_stower))
        need = {
            "induct": inductors,
            "stow": stowers,
            "problem_solve": lab.problem_solvers,
            "high_value": lab.high_value_associates,
            "pick": lab.dedicated_pickers,
        }
        return {
            "routes": routes,
            "spr": round(ofd / routes, 1),
            "tph": round(tph),
            "by_role": need,
            "headcount": sum(need.values()),
            "labor_hours": round(sum(need.values()) * 8, 1),
        }

    # --- people: expected show, opportunities, labor plan v2, rotation -------------------

    def available(self) -> list[dict]:
        return [
            p
            for p in self.roster
            if (p["scheduled"] and not p["called_out"] and not p["vto"] and not p["flex"])
            or p["vet"]
        ]

    def expected_show(self) -> dict:
        att = self.c.labor.attendance_rate
        sched = [
            p
            for p in self.roster
            if p["scheduled"] and not p["called_out"] and not p["vto"] and not p["flex"]
        ]
        vet = [p for p in self.roster if p["vet"]]
        opps = self.opportunities.items
        open_ = [o for o in opps if o["status"] == "open"]
        exp_open = 0.0
        for o in open_:
            remaining = max(0, o["headcount"] - len(o["accepted"]))
            likely = len(self.opportunities.eligible(o["type"])) * self.opportunities.submit_p(
                o["type"], o["posted_at"], o["frame_start"]
            )
            exp_open += min(remaining, likely) * (1 if o["type"] == "VET" else -1)
        return {
            "scheduled": len(sched),
            "called_out": sum(1 for p in self.roster if p["called_out"]),
            "vto_accepted": sum(1 for p in self.roster if p["vto"]),
            "vet_accepted": len(vet),
            "pending_offers": len(open_),
            "expected": round(len(sched) * att + len(vet) + exp_open, 1),
        }

    @property
    def offers(self) -> list[dict]:
        """Per-associate view of the opportunities (v1 compatibility): every
        submission, with whether the station accepted it."""
        out = []
        for o in self.opportunities.items:
            acc = {a["login"]: a["clock"] for a in o["accepted"]}
            for sub in o["submitted"]:
                status = (
                    "accepted"
                    if sub["login"] in acc
                    else "pending"
                    if o["status"] == "open"
                    else "declined"
                )
                out.append(
                    {
                        "login": sub["login"],
                        "type": o["type"].lower(),
                        "opportunity": o["id"],
                        "frame": o["frame"],
                        "offered": o["posted_at"],
                        "offered_clock": o["posted_clock"],
                        "submitted_clock": sub["clock"],
                        "status": status,
                        "responded_clock": acc.get(sub["login"]) or o.get("closed_clock"),
                        "source": o["source"],
                    }
                )
        return out

    def offer(self, kind: str, n: int, source: str) -> str:
        """v1 entry point → post an opportunity (associates submit, station accepts)."""
        return self.opportunities.post(kind.upper(), n, None, source)

    def labor_plan(self) -> dict:
        """Tomorrow's labor plan v2 from the truckfile as currently known."""
        ofd = self.known_ofd()
        sched = sum(
            1
            for p in self.roster
            if p["scheduled"] and not p["called_out"] and not p["vto"] and not p["flex"]
        ) + sum(1 for p in self.roster if p["vet"])
        return lp.build_plan(
            self.c,
            ofd["ofd_volume"],
            scheduled={"Single Cycle": sched},
            attendance={"Single Cycle": self.c.labor.attendance_rate},
            planned_rollover=ofd["carryover"],
            planned_volume=ofd["linehaul_in_time"],
        )

    def headcount_plan(self, label: str) -> dict:
        ofd = self.known_ofd()
        need = self.needs(ofd["ofd_volume"])
        plan = self.labor_plan()
        show = self.expected_show()
        frames = {f["frame"]: f for f in lp.frame_gaps(plan)}
        main = frames.get("Single Cycle", {"shortfall": 0.0, "surplus": 0.0})
        gap = main["shortfall"] if main["shortfall"] > 0 else -main["surplus"]
        out = {
            "label": label,
            "clock": _clock(self.env.now / 60),
            "truckfile_version": self.truckfile_version,
            "ofd": ofd,
            "needs": need,
            "show": show,
            "gap": round(gap, 1),
            "frames": list(frames.values()),
            "offers_made": None,
        }
        made = []
        for rec in self.opportunities.recommendations():
            open_same = [
                o
                for o in self.opportunities.items
                if o["status"] == "open" and o["type"] == rec["type"] and o["frame"] == rec["frame"]
            ]
            if open_same:
                continue
            eligible = len(self.opportunities.eligible(rec["type"]))
            if eligible == 0:
                continue
            # post enough headcount to cover the gap; acceptance is capped at the need
            n = rec["headcount"]
            made.append(self.opportunities.post(rec["type"], n, rec["frame"], "manager"))
        out["offers_made"] = "; ".join(made) if made else None
        return out

    def _slots(self, plan: dict) -> list[tuple[str, str]]:
        hours = plan["hour_minutes"]
        sort_idx = [
            i
            for i, h in enumerate(hours)
            if self.c.induct.start_minute <= h < self.c.cycle.pick_start_minute
        ]
        rows = {r["path"]: r["hc"] for g in plan["groups"] for r in g["paths"]}
        slots: list[tuple[str, str]] = []
        for path in SORT_PATHS:
            peak = max((rows[path][i] for i in sort_idx), default=0.0)
            n = math.ceil(peak - 0.15) if peak > 0 else 0
            if path == "sort_problem_solve":
                n = max(n, self.c.labor.problem_solvers)
            for k in range(n):
                slots.append((path, f"{PROCESS_PATHS[path]['label']} #{k + 1}"))
        for k in range(self.c.labor.high_value_associates):
            slots.append(("high_value", f"HV cage #{k + 1}"))
        for k in range(self.c.labor.dedicated_pickers):
            slots.append(("pick", f"Pick (dedicated) #{k + 1}"))
        return slots

    def rerun_rotation(self, source: str) -> str:
        if self.plan is None:
            return "no-op: no plan yet — rotation runs with tomorrow's plan"
        plan = self.labor_plan()
        assignments, stats = rot.assign(
            self.available(),
            self._slots(plan),
            self.c.labor_plan.heavy_days_disallow,
            self.cfg.max_consecutive_same_role,
        )
        self._apply_rotation(assignments, stats)
        self.rotation_stats["rerun"] = True
        return (
            f"shift rotation re-run ({source}): {stats['filled']}/{stats['slots']} slots, "
            f"compliance {stats['compliance']:.0%}, {stats['unfilled']} unfilled"
        )

    def _apply_rotation(self, assignments: list[dict], stats: dict) -> None:
        self.rotation_runs += 1
        self.rotation = rot.table(
            [p for p in self.roster if not p["flex"] or p["vet"]],
            assignments,
            self.c.labor_plan.heavy_days_disallow,
        )
        self.rotation_stats = {
            **stats,
            "runs": self.rotation_runs,
            "clock": _clock(self.env.now / 60),
        }
        if self.plan is not None:
            self.plan["assignments"] = assignments
            self.plan["rotation_violations"] = stats["violations"]
            self.plan["rotation_compliance"] = stats["compliance"]

    def build_plan(self, label: str) -> dict:
        hc = self.headcount_plan(label)
        need = hc["needs"]
        plan_v2 = self.labor_plan()
        rng = random.Random(f"tomorrow-routes:{self.c.seed}:{need['routes']}")
        ofd = hc["ofd"]["ofd_volume"]
        weights = [rng.lognormvariate(0, 0.25) for _ in range(need["routes"])]
        total_w = sum(weights)
        route_vol = [round(ofd * w / total_w) for w in weights]
        aisles = self.twin.aisles
        load = {a: 0 for a in aisles}
        routes_in = {a: 0 for a in aisles}
        for v in sorted(route_vol, reverse=True):  # LPT balancing
            a = min(aisles, key=lambda x: (load[x], x))
            load[a] += v
            routes_in[a] += 1
        slots = self._slots(plan_v2)
        assignments, stats = rot.assign(
            self.available(),
            slots,
            self.c.labor_plan.heavy_days_disallow,
            self.cfg.max_consecutive_same_role,
        )
        # stow zones: contiguous aisles with ~equal volume per planned stower
        stowers = max(1, sum(1 for a in assignments if a["path"] == "stow" and a["login"]))
        per = sum(load.values()) / stowers
        zones: list[tuple[list[str], int]] = [([], 0) for _ in range(stowers)]
        cum = 0.0
        for a in aisles:
            k = min(len(zones) - 1, int((cum + load[a] / 2) / per)) if per else 0
            zs, v = zones[k]
            zones[k] = ([*zs, a], v + load[a])
            cum += load[a]
        zones = [z for z in zones if z[0]]
        zi = 0
        for a in assignments:
            if a["path"] == "stow" and a["login"] and zi < len(zones):
                z = zones[zi][0]
                a["where"] = f"Stow Z{zi + 1} ({z[0]}–{z[-1]})"
                zi += 1
        version = (self.plan["version"] + 1) if self.plan else 1
        self.plan = {
            **hc,
            "version": version,
            "labor_plan": plan_v2,
            "aisles": [{"aisle": a, "volume": load[a], "routes": routes_in[a]} for a in aisles],
            "zones": [
                {"zone": f"Z{i + 1}", "aisles": f"{z[0]}–{z[-1]}", "volume": v}
                for i, (z, v) in enumerate(zones)
            ],
            "assignments": assignments,
            "rotation_violations": stats["violations"],
            "rotation_compliance": stats["compliance"],
            "callouts_seen": len(self.callouts),
        }
        self._apply_rotation(assignments, stats)
        self.plan_history.append(
            {
                "version": version,
                "clock": self.plan["clock"],
                "label": label,
                "truckfile_version": self.truckfile_version,
                "ofd_volume": ofd,
                "headcount_needed": need["headcount"],
                "expected": hc["show"]["expected"],
                "gap": hc["gap"],
            }
        )
        t = plan_v2["totals"]
        self.twin.notify(
            "manager",
            "plan",
            "info",
            f"Tomorrow's plan v{version} published",
            f"OFD {ofd:,} · {need['routes']} routes · SPR {need['spr']} · "
            f"show {t['show_hours']} h vs needed {t['needed_hours']} h · "
            f"rotation {self.plan['rotation_compliance']:.0%}.",
        )
        return self.plan

    # --- task effects -----------------------------------------------------------------

    def _do(self, t: dict) -> str:
        kind = t["kind"]
        if kind == "floor_close":
            open_aisles = sum(1 for x in self.twin.aisles if x not in self.twin.swept)
            return f"floor closed; {open_aisles} aisle(s) left for the scrub"
        if kind == "gtdr":
            g = next(x for x in self.gtdr if x["gtdr_id"] == t["gtdr_id"])
            g["status"], g["filed_clock"] = "filed", _clock(self.env.now / 60)
            return f"{g['gtdr_id']} filed"
        if kind == "ferry_check":
            return self.ferry_check()
        if kind == "publish_truckfile":
            self.ferry_check()
            self.truckfile_version = 1
            self.final_published_at = self.env.now / 60
            ofd = self.known_ofd()
            self.twin.notify(
                "manager",
                "truckfile_final",
                "info",
                "Final truckfile published",
                f"{len(self.trips)} trips; known OFD volume {ofd['ofd_volume']:,} "
                f"({ofd['linehaul_at_risk']:,} at risk of arriving after pick start).",
            )
            return f"final truckfile v1 published (OFD {ofd['ofd_volume']:,})"
        if kind == "in_station_scrub":
            return self._in_station_scrub()
        if kind == "on_road_scrub":
            return self._on_road_scrub()
        if kind == "headcount":
            hc = self.headcount_plan("initial headcount")
            self.headcount = hc
            return f"need {hc['needs']['headcount']} vs expected {hc['show']['expected']}: " + (
                hc["offers_made"] or "no offers needed"
            )
        if kind == "build_plan":
            p = self.build_plan("daily plan")
            return f"plan v{p['version']} built (rotation {p['rotation_compliance']:.0%})"
        if kind in ("final_review", "replan"):
            stale = self.plan is None or self.plan["truckfile_version"] != self.truckfile_version
            hc = self.headcount_plan("review")
            changed = (
                stale
                or abs(hc["gap"]) > 0.5
                or (self.plan and len(self.callouts) != self.plan.get("callouts_seen", 0))
            )
            if not changed and self.plan:
                return "plan still valid — no change"
            if self.plan is None and self.env.now / 60 < self.cfg.build_plan_minute:
                return "needs refreshed; " + (hc["offers_made"] or "no offers needed")
            p = self.build_plan("re-plan" if kind == "replan" else "final review")
            return f"re-planned → v{p['version']} ({hc['offers_made'] or 'no new offers'})"
        return "done"

    # --- the next day ---------------------------------------------------------------

    def next_day_config(self):
        """Tomorrow's twin config, built from the final truckfile (as known now)
        and today's carry-over and plan. What the station hasn't learned yet
        (unrevealed ferry revisions) still happens — and is revealed during
        the next day, an hour and a half before the trip was due."""
        from app.simulation.station_ops.config import FerryRevision, LinehaulPlan
        from app.simulation.station_ops.plan import random_disruptions

        if self.final_published_at is None:
            raise ValueError("no final truckfile yet — the next day is planned from it")
        truth: dict[int, dict] = {}
        for r in self.revisions:
            truth.setdefault(r["trip"], {})[r["field"]] = (r["value"], r["revealed"])
        linehauls = []
        for i, t in enumerate(self.trips):
            tv = truth.get(i, {})
            volume, _ = tv.get("known_volume", (t["known_volume"], True))
            if volume <= 0:
                continue
            delay, delay_known = tv.get("known_delay", (t["known_delay"], True))
            cancelled, _ = tv.get("known_cancelled", (t["known_cancelled"], True))
            revisions = []
            if delay and delay_known:
                revisions = [FerryRevision(reveal_minute=0, delay_minutes=delay)]
            elif delay:
                revisions = [
                    FerryRevision(
                        reveal_minute=max(0.0, t["planned_arrival"] - 90), delay_minutes=delay
                    )
                ]
            linehauls.append(
                LinehaulPlan(
                    trip_id=t["trip_id"],
                    origin=t["origin"],
                    planned_arrival_minute=t["planned_arrival"],
                    delay_minutes=delay,
                    revisions=revisions,
                    cancelled=bool(cancelled),
                    volume=volume,
                    via_ferry=t["via_ferry"],
                    ferry_sailing=t["sailing"],
                    delay_reason=next(
                        (
                            r["why"]
                            for r in self.revisions
                            if r["trip"] == i and r["field"] == "known_delay"
                        ),
                        None,
                    ),
                )
            )
        cfg = self.c.model_copy(deep=True)
        seed = self.c.seed + 1
        cfg.seed, cfg.ofd_date, cfg.day = seed, self.tomorrow, self.c.day + 1
        cfg.name, cfg.source = "next_day", "next_day"
        cfg.truckfile_version = self.truckfile_version
        cfg.linehauls = linehauls
        cfg.disruptions = random_disruptions(seed)
        cfg.driver_seed, cfg.driver_overrides, cfg.route_overrides = None, {}, {}
        planned = sum(t.volume for t in linehauls if not t.cancelled) or 1
        carry = self.known_ofd()["carryover"]
        cfg.backlog.rollover_share = min(0.5, carry / planned)
        if self.plan:
            filled = Counter(a["role"] for a in self.plan["assignments"] if a["login"])
            cfg.induct.lines = max(1, filled["induct"])
            cfg.stow.stowers = max(1, filled["stow"])
            cfg.labor.problem_solvers = filled["problem_solve"]
            cfg.labor.high_value_associates = max(1, filled["high_value"])
            cfg.labor.dedicated_pickers = filled["pick"]
            cfg.outbound.routes = self.plan["needs"]["routes"]
        offered = {o["login"] for o in self.offers}
        unoffered = sum(1 for p in self.roster if p["flex"] and p["login"] not in offered)
        cfg.carried_work_items = [
            {k: v for k, v in it.items() if k not in ("id",)}
            for it in self.twin.work_items.open_items()
            if it["kind"] not in ("agent_recommendation",)
        ][:40]
        cfg.labor.flex_pool = max(2, unoffered // 2)
        cfg.description = (
            f"Day {cfg.day} ({self.tomorrow.isoformat()}), simulated from truckfile "
            f"v{self.truckfile_version} and plan v{self.plan['version'] if self.plan else 0} of "
            f"the previous day: {len(linehauls)} trips, {carry:,} carry-over packages, "
            f"{cfg.stow.stowers} stowers planned."
        )
        return cfg

    # --- readiness (evaluated against tomorrow's full truth) ----------------------------

    def evaluate(self) -> dict:
        """How ready tomorrow is, judged against the *true* truckfile (every
        revision, revealed or not). Proposed measure — not an org metric."""
        saved = [(t, dict(t)) for t in self.trips]
        for r in self.revisions:
            self.trips[r["trip"]][r["field"]] = r["value"]
        true_ofd = self.known_ofd()["ofd_volume"]
        true_need = self.needs(true_ofd)["headcount"]
        for t, old in saved:
            t.update(old)
        show = self.expected_show()["expected"]
        planned = self.plan["needs"]["headcount"] if self.plan else 0
        return {
            "true_ofd_volume": true_ofd,
            "planned_ofd_volume": self.plan["ofd"]["ofd_volume"] if self.plan else None,
            "true_headcount_needed": true_need,
            "planned_headcount_needed": planned,
            "expected_show": show,
            "staffing_gap": round(true_need - show, 1),
            "unrevealed_revisions": sum(1 for r in self.revisions if not r["revealed"]),
            "plan_on_latest_truckfile": bool(
                self.plan and self.plan["truckfile_version"] == self.truckfile_version
            ),
            "rotation_compliance": self.plan["rotation_compliance"] if self.plan else None,
            "gtdr_open": sum(1 for g in self.gtdr if g["status"] != "filed"),
        }


def _iv(kind: str, **kw):
    from app.simulation.station_ops.model import Intervention

    return Intervention(kind=kind, at_minute=0, **kw)
