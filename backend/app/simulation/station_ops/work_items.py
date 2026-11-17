"""Unified work items (HANDOFF_V2 E10, ADR-0015).

Everything that needs a person becomes a work item with a category, a
priority, an owner, who started it, and an expiry. That covers floor
notifications, close-out tasks, problem-solve approvals, scrubs and
missing/lost reviews, and agent recommendations (added by the runtime).
Items expire deterministically by sim time; open items carry over to the
next day.

The SLA minutes and the category mapping are proposed, not documented.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from app.simulation.station_ops.model import StationOpsTwin

CATEGORIES = (
    "Induct",
    "Sort",
    "Pick & Stage",
    "Dispatch",
    "Fleet",
    "Safety",
    "Ops Updates",
    "People",
)

#: notification / task kind → (category, process, priority 1=high … 3=low, SLA minutes)
KIND_MAP: dict[str, tuple[str, str, int, float]] = {
    "wrong_staging_scan": ("Pick & Stage", "Stage", 1, 10),
    "staging_change": ("Dispatch", "Dispatch", 2, 20),
    "bag_not_loaded": ("Pick & Stage", "Pick", 1, 15),
    "van_grounded": ("Fleet", "Dispatch", 1, 20),
    "vsa_minor": ("Fleet", "Dispatch", 3, 30),
    "van_replacement": ("Fleet", "Dispatch", 2, 45),
    "driver_late": ("Dispatch", "Dispatch", 2, 20),
    "callout": ("People", "Labor", 2, 120),
    "plan": ("Ops Updates", "Planning", 3, 180),
    "truckfile_final": ("Ops Updates", "Inbound", 3, 120),
    "truckfile_revised": ("Ops Updates", "Inbound", 1, 60),
    "closeout": ("Ops Updates", "Close-out", 3, 60),
    "cycle_pick_started": ("Induct", "Induct", 1, 20),
    "damaged_approval": ("Sort", "Problem solve", 2, 45),
    "gtdr": ("Dispatch", "Yard", 2, 60),
    "ferry_check": ("Ops Updates", "Inbound", 2, 30),
    "publish_truckfile": ("Ops Updates", "Inbound", 1, 60),
    "in_station_scrub": ("Ops Updates", "Package summary", 2, 120),
    "on_road_scrub": ("Ops Updates", "Package summary", 2, 120),
    "headcount": ("People", "Labor", 1, 60),
    "build_plan": ("People", "Labor", 1, 90),
    "final_review": ("People", "Labor", 2, 60),
    "replan": ("People", "Labor", 1, 30),
    "floor_close": ("Safety", "Close-out", 2, 30),
    "review_missing": ("Ops Updates", "Package summary", 2, 240),
    "review_lost": ("Ops Updates", "Package summary", 2, 240),
    "agent_recommendation": ("Ops Updates", "Agent", 2, 30),
}
DEFAULT = ("Ops Updates", "Station", 3, 60)


def category_for(kind: str) -> tuple[str, str, int, float]:
    return KIND_MAP.get(kind, DEFAULT)


class WorkItemStore:
    def __init__(self, twin: StationOpsTwin):
        self.twin = twin
        self.items: list[dict] = []
        self._id = 0

    def _clock(self, minute: float) -> str:
        from app.simulation.station_ops.model import clock

        return clock(minute)

    def add(
        self,
        *,
        kind: str,
        title: str,
        category: str | None = None,
        process: str | None = None,
        priority: int | None = None,
        owner: str = "supervisor",
        started_by: str = "system",
        associate: str | None = None,
        ref: str | None = None,
        sla_minutes: float | None = None,
        source_ref: dict | None = None,
    ) -> dict:
        cat, proc, prio, sla = category_for(kind)
        now = self.twin.env.now / 60
        self._id += 1
        item = {
            "id": f"WI-{self._id:04d}",
            "kind": kind,
            "category": category or cat,
            "process": process or proc,
            "priority": priority or prio,
            "title": title,
            "owner": owner,
            "associate": associate,
            "started_by": started_by,
            "ref": ref,
            "created": round(now, 2),
            "created_clock": self._clock(now),
            "expires_at": round(now + (sla_minutes or sla), 2),
            "expires_clock": self._clock(now + (sla_minutes or sla)),
            "state": "pending",
            "closed_at": None,
            "closed_clock": None,
            "resolution": None,
            "carried": False,
            "source_ref": source_ref or {},
        }
        self.items.append(item)
        if len(self.items) > 1500:
            done = [x for x in self.items if x["state"] != "pending"]
            for x in done[:300]:
                self.items.remove(x)
        return item

    def carry(self, item: dict) -> None:
        """An item still open at the end of the previous day."""
        self._id += 1
        self.items.append(
            {
                **item,
                "id": f"WI-{self._id:04d}",
                "carried": True,
                "state": "pending",
                "created": 0.0,
                "created_clock": "prev. day",
                "expires_at": 600.0,
                "expires_clock": self._clock(600.0),
            }
        )

    def _close(self, item: dict, state: str, resolution: str) -> None:
        if item["state"] != "pending":
            return
        now = self.twin.env.now / 60
        item["state"], item["resolution"] = state, resolution
        item["closed_at"], item["closed_clock"] = round(now, 2), self._clock(now)

    def resolve_item(self, item: dict, resolution: str = "done") -> None:
        self._close(item, "done", resolution)

    def resolve(self, kind: str, ref: str | None = None, resolution: str = "done") -> int:
        n = 0
        for it in self.items:
            if (
                it["state"] == "pending"
                and it["kind"] == kind
                and (ref is None or it["ref"] == ref)
            ):
                self._close(it, "done", resolution)
                n += 1
        return n

    def by_id(self, item_id: str) -> dict | None:
        return next((x for x in self.items if x["id"] == item_id), None)

    def dismiss(self, item_id: str, who: str = "user") -> dict | None:
        it = self.by_id(item_id)
        if it:
            self._close(it, "dismissed", f"dismissed by {who}")
        return it

    def complete(self, item_id: str, who: str = "user") -> dict | None:
        it = self.by_id(item_id)
        if it:
            self._close(it, "done", f"completed by {who}")
        return it

    def tick(self) -> None:
        now = self.twin.env.now / 60
        for it in self.items:
            if it["state"] == "pending" and now >= it["expires_at"]:
                it["state"] = "expired"
                it["closed_at"], it["closed_clock"] = round(now, 2), self._clock(now)

    def open_items(self) -> list[dict]:
        return [x for x in self.items if x["state"] == "pending"]

    def summary(self) -> dict:
        today = [x for x in self.items]
        pending = [x for x in today if x["state"] == "pending"]
        by_cat = {c: sum(1 for x in pending if x["category"] == c) for c in CATEGORIES}
        return {
            "pending": len(pending),
            "by_category": by_cat,
            "high_priority": sum(1 for x in pending if x["priority"] == 1),
            "completed_today": sum(1 for x in today if x["state"] == "done"),
            "expired_today": sum(1 for x in today if x["state"] == "expired"),
            "dismissed_today": sum(1 for x in today if x["state"] == "dismissed"),
            "carried_over": sum(1 for x in pending if x["carried"]),
        }
