"""Shift knowledge base for the Station Assistant (the "R" in RAG).

Every question is answered against a corpus rebuilt from the live session:
metric definitions and values, today's linehauls and ferry revisions,
tomorrow's truckfile and its revision log, GTDRs, every action and agent
decision (with its rationale), disruptions, notifications, late routes,
driver/VSA records, the sweep log, VET/VTO offers, call-outs, the plan and
the event log. Retrieval is BM25 with a small domain synonym map — local,
deterministic, no embedding model or network needed.

Each document carries its kind, a title and a sim clock so answers can cite
where a fact came from.
"""

import math
import re
from collections import Counter

from pydantic import BaseModel

from app.simulation.station_ops.model import StationOpsTwin, clock
from app.simulation.station_ops.snapshot import METRIC_DEFINITIONS, build_snapshot

_STOP = set(
    "a an the of to in on at for and or is are was were be been it its this that what which who "
    "how why when where did do does we our us you i me my with by from as about any all so up "
    "tell give show explain can could would should please there their them than then".split()
)
SYNONYMS = {
    "dea": ["delivery", "estimate", "accuracy", "rollover", "missed", "attempted"],
    "otd": ["departure", "departed", "late", "depart"],
    "truck": ["linehaul", "trailer", "trip"],
    "trucks": ["linehaul", "trailer", "trip"],
    "truckfile": ["linehaul", "trip", "revision", "ferry"],
    "ferry": ["sailing", "port", "ferry"],
    "ferries": ["ferry", "sailing", "port"],
    "vet": ["voluntary", "extra", "flex", "offer"],
    "vto": ["voluntary", "time", "off", "offer"],
    "associates": ["associate", "labor", "headcount"],
    "staff": ["associate", "labor", "headcount"],
    "volume": ["ofd", "packages", "volume"],
    "tomorrow": ["tomorrow", "plan", "next"],
    "gtdr": ["gtdr", "trailer", "dock", "release"],
    "low": ["missed", "late", "below"],
    "drop": ["missed", "late", "below"],
    "van": ["vsa", "grounded", "driver"],
    "cycle": ["cycle", "pick", "induct", "blocked"],
    "expired": ["expired", "work", "item"],
    "gaylord": ["container", "gaylord"],
    "pallet": ["container", "pallet"],
    "vans": ["vsa", "grounded", "driver"],
}


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text.lower()) if t not in _STOP]


class Doc(BaseModel):
    id: str
    kind: str
    title: str
    text: str
    clock: str | None = None


def build_corpus(tw: StationOpsTwin, loop) -> list[Doc]:  # noqa: C901
    """Caller holds the session lock."""
    docs: list[Doc] = []
    add = docs.append
    snap = build_snapshot(tw, 0)
    c = tw.config
    for key, mt in snap.metrics.items():
        d = METRIC_DEFINITIONS.get(key, {})
        val = mt.value
        shown = "—" if val is None else f"{val * 100:.1f}%" if mt.unit == "ratio" else f"{val:,.1f}"
        add(
            Doc(
                id=f"metric:{key}",
                kind="metric",
                title=f"{d.get('label', key)} = {shown}",
                text=f"{d.get('label', key)} ({key}) is {shown}"
                + (f", target {mt.target}" if mt.target is not None else "")
                + f". Definition ({d.get('status', 'proposed')}): {d.get('formula', '')}",
                clock=snap.clock,
            )
        )
    now = tw.now_minute
    for i, plan in enumerate(c.linehauls):
        t = tw.trips[i]
        add(
            Doc(
                id=f"trip:{plan.trip_id}",
                kind="linehaul",
                title=f"Linehaul {plan.trip_id} ({plan.origin})",
                text=f"Linehaul trip {plan.trip_id} truck from {plan.origin}"
                + (f" via ferry sailing {plan.ferry_sailing}" if plan.via_ferry else " by road")
                + f", {plan.volume} packages, planned {clock(plan.planned_arrival_minute)}, "
                f"known delay {plan.known_delay(now):.0f} min, status {t.status}"
                + (f", arrived {clock(t.arrived_at / 60)} door {t.door}" if t.arrived_at else "")
                + (f", reason {plan.delay_reason}" if plan.delay_reason else ""),
                clock=clock(t.arrived_at / 60) if t.arrived_at else None,
            )
        )
    co = tw.closeout
    for t in co.trips:
        add(
            Doc(
                id=f"tomorrow:{t['trip_id']}",
                kind="truckfile",
                title=f"Tomorrow's truckfile trip {t['trip_id']}",
                text=f"Tomorrow truckfile trip {t['trip_id']} from {t['origin']}"
                + (f" ferry sailing {t['sailing']}" if t["via_ferry"] else " road")
                + f", volume {t['known_volume']}, delay {t['known_delay']:.0f} min"
                + (", cancelled" if t["known_cancelled"] else "")
                + (", added after final" if t["added"] else "")
                + f", last ferry check {t['last_checked'] or 'never'}",
            )
        )
    for x in co.truckfile_log:
        add(
            Doc(
                id=f"rev:{x['clock']}:{x['trip_id']}",
                kind="truckfile",
                title=f"Truckfile revision {x['trip_id']}",
                text=f"Truckfile revision for tomorrow: {x['trip_id']} {x['field']} {x['before']} → "
                f"{x['after']} because {x['why']}, learned via {x['how']}"
                + (f", after the final truckfile (v{x['version']})" if x["after_final"] else ""),
                clock=x["clock"],
            )
        )
    for g in co.gtdr:
        add(
            Doc(
                id=f"gtdr:{g['gtdr_id']}",
                kind="gtdr",
                title=f"{g['gtdr_id']} Global Trailer Dock and Release",
                text=f"GTDR (global trailer dock and release) {g['gtdr_id']} "
                f"{g['direction'].replace('_', ' ')} trailer {g['trailer']} {g['place']} scheduled "
                f"{g['scheduled']} actual {g['actual']} delay {g['delay_minutes']} min, "
                f"{g['units']} units, {g['pallets']} pallets, seal {g['seal']}: {g['reason']}; "
                f"status {g['status']}",
                clock=g["opened_clock"],
            )
        )
    for o in co.offers:
        add(
            Doc(
                id=f"offer:{o['type']}:{o['login']}",
                kind="offer",
                title=f"{o['type'].upper()} offer to {o['login']}",
                text=f"{o['type'].upper()} offer for tomorrow to associate {o['login']} at "
                f"{o['offered_clock']} by {o['source']}: {o['status']}"
                + (f" at {o['responded_clock']}" if o["responded_clock"] else ""),
                clock=o["offered_clock"],
            )
        )
    for x in co.callouts:
        add(
            Doc(
                id=f"callout:{x['login']}",
                kind="offer",
                title=f"Call-out {x['login']}",
                text=f"Associate {x['login']} called out for tomorrow",
                clock=x["clock"],
            )
        )
    for t in co.tasks:
        add(
            Doc(
                id=f"task:{t['id']}",
                kind="closeout",
                title=f"{t['owner'].title()} task: {t['title']}",
                text=f"Close-out {t['owner']} task {t['title']} ({t['status']})"
                + (f": {t['result']}" if t["result"] else ""),
                clock=t.get("finished_clock") or t["created_clock"],
            )
        )
    for a in tw.applied:
        add(
            Doc(
                id=f"applied:{a['minute']:.2f}:{a['kind']}",
                kind="action",
                title=f"{a['kind'].replace('_', ' ')} ({a['source']})",
                text=f"Action {a['kind'].replace('_', ' ')} by {a['source']}: {a['effect']}",
                clock=a["clock"],
            )
        )
    for a in loop.actions[-300:]:
        add(
            Doc(
                id=f"agent:{a.id}",
                kind="agent",
                title=f"{a.agent_label}: {a.risk.risk_type.replace('_', ' ')} ({a.status})",
                text=f"{a.agent_label} saw {a.risk.summary} Decision ({a.kind}, {a.status}): "
                f"{a.chosen or 'none'}. {a.rationale} " + " ".join(a.applied_effects),
                clock=a.clock,
            )
        )
    for d in tw.disruptions_seen:
        add(
            Doc(
                id=f"disruption:{d['clock']}:{d['kind']}",
                kind="disruption",
                title=f"{d['kind'].replace('_', ' ')} at {d['clock']}",
                text=f"Disruption {d['kind'].replace('_', ' ')} target {d['target']} magnitude "
                f"{d['magnitude']} from {d['clock']}",
                clock=d["clock"],
            )
        )
    for n in tw.notifications[-200:]:
        add(
            Doc(
                id=f"notification:{n['id']}",
                kind="notification",
                title=n["title"],
                text=f"Notification to {n['audience']}: {n['title']}. {n['message']}",
                clock=n["clock"],
            )
        )
    for r in tw.routes:
        if r.departed_at is not None and r.departed_at > r.planned_depart:
            add(
                Doc(
                    id=f"route:{r.route_id}",
                    kind="route",
                    title=f"{r.route_id} departed late",
                    text=f"Route {r.route_id} ({r.dsp}) departed {clock(r.departed_at / 60)}, "
                    f"{(r.departed_at - r.planned_depart) / 60:.0f} min late (planned "
                    f"{clock(r.planned_depart / 60)}), {r.not_attempted} not attempted",
                    clock=clock(r.departed_at / 60),
                )
            )
    for w in tw.work_items.items[-300:]:
        add(
            Doc(
                id=f"work:{w['id']}",
                kind="work_item",
                title=f"Work item {w['id']}: {w['title']}",
                text=f"Work item {w['category']} {w['process']} {w['title']} owner {w['owner']} "
                f"started by {w['started_by']} state {w['state']} expires {w['expires_clock']}"
                + (f" resolution {w['resolution']}" if w["resolution"] else ""),
                clock=w["created_clock"],
            )
        )
    for x in tw.cycle_changes:
        add(
            Doc(
                id=f"cycle:{x['clock']}:{x['action']}",
                kind="cycle",
                title=f"Cycle action {x['action'].replace('_', ' ')}",
                text=f"Cycle pick start induct blocked action {x['action'].replace('_', ' ')} "
                + " ".join(f"{k} {v}" for k, v in x.items() if k not in ("clock", "action")),
                clock=x["clock"],
            )
        )
    for o in co.opportunities.items:
        add(
            Doc(
                id=f"opp:{o['id']}",
                kind="offer",
                title=f"{o['type']} opportunity {o['id']} {o['frame']}",
                text=f"{o['type']} opportunity for tomorrow {o['frame']} time frame {o['time_frame']} "
                f"posted {o['posted_clock']} by {o['source']}, sign-up window {o['status']} until "
                f"{o['window_close_clock']}: {len(o['submitted'])} submitted, {len(o['accepted'])} accepted "
                f"of {o['headcount']} headcount",
                clock=o["posted_clock"],
            )
        )
    for r in tw.network_missorts[-100:]:
        add(
            Doc(
                id=f"nm:{r['id']}",
                kind="quality",
                title=f"Network missort {r['id']}",
                text=f"Network missort {r['reason'].replace('_', ' ')} from trip {r['trip']} container "
                f"{r['container']} status {r['status'].replace('_', ' ')}",
            )
        )
    for s in tw.sweep_log:
        add(
            Doc(
                id=f"sweep:{s['clock']}:{s['route_id']}",
                kind="sweep",
                title=f"Sweep {s['aisle']} → {s['outcome']}",
                text=f"Sweep found {s['packages']} {s['route_id']} package(s) in aisle {s['aisle']} "
                f"({', '.join(s['reasons'])}): {s['outcome'].replace('_', ' ')}",
                clock=s["clock"],
            )
        )
    for e in list(tw.events)[-200:]:
        add(
            Doc(
                id=f"event:{e['minute']:.2f}:{e['kind']}",
                kind="event",
                title=e["message"][:80],
                text=f"{e['kind']}: {e['message']}",
                clock=e["clock"],
            )
        )
    return docs


class Index:
    def __init__(self, docs: list[Doc]):
        self.docs = docs
        self.toks = [tokens(d.title + " " + d.text) for d in docs]
        self.df: Counter = Counter()
        for t in self.toks:
            self.df.update(set(t))
        self.avg = sum(len(t) for t in self.toks) / max(1, len(self.toks))

    def search(self, query: str, k: int = 6, kinds: set[str] | None = None) -> list[Doc]:
        q = tokens(query)
        q += [s for w in list(q) for s in SYNONYMS.get(w, [])]
        n = len(self.docs)
        scored = []
        for doc, toks in zip(self.docs, self.toks, strict=True):
            if kinds and doc.kind not in kinds:
                continue
            tf = Counter(toks)
            score = 0.0
            for w in set(q):
                if w not in tf:
                    continue
                idf = math.log(1 + (n - self.df[w] + 0.5) / (self.df[w] + 0.5))
                f = tf[w]
                score += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * len(toks) / self.avg))
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda x: -x[0])
        return [d for _, d in scored[:k]]
