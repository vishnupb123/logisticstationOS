"""Deterministic shift analyses behind the Station Assistant.

Each function reads the live twin (the caller holds the session lock) and
returns an `Analysis`: a headline, titled sections of plain-language lines,
the facts behind them (numbered, for LLM grounding), and the sources they
came from. Every number here is *computed* from state — the LLM may only
rephrase these facts, never add to them (app/runtime/chat.py validates that).

Root-cause attribution is rule-based and stated (e.g. a rolled-over package
that arrived after pick start is attributed to its late linehaul). Impact of
decisions is measured by replaying the same day without them — a simulated
counterfactual, reported as such.
"""

from collections import Counter, defaultdict

from pydantic import BaseModel

from app.simulation.station_ops.model import Intervention, StationOpsTwin, clock
from app.simulation.station_ops.snapshot import METRIC_DEFINITIONS, build_snapshot, run_station_day

LOAD_WINDOW_S = 15 * 60

DEA_LEVERS = {
    "extend_cutoff",
    "add_stowers",
    "add_pickers",
    "open_induct_line",
    "priority_late_linehauls",
    "move_associates",
    "resequence_unload",
    "direct_sweep",
    "prioritize_route",
    "sideline_route",
    "start_scrub",
    "force_induct",
    "change_cycle",
    "enable_cycle",
    "rebalance_finger",
    "approve_damaged",
}
OTD_LEVERS = {
    "notify_drivers",
    "reassign_standby",
    "move_route_wave",
    "request_replacement_van",
    "restage_cart",
    "add_yard_marshal",
    "prioritize_route",
    "add_pickers",
    "notify_swipe_finish",
}
PLAN_LEVERS = {
    "check_ferry",
    "replan_next_day",
    "offer_vet",
    "offer_vto",
    "draft_gtdr",
    "post_opportunity",
    "close_window",
    "rerun_rotation",
}


class Section(BaseModel):
    title: str
    lines: list[str]


class Source(BaseModel):
    kind: str
    title: str
    clock: str | None = None


class Analysis(BaseModel):
    topic: str
    title: str
    headline: str
    sections: list[Section] = []
    sources: list[Source] = []

    def facts(self) -> list[str]:
        out = [self.headline]
        for s in self.sections:
            out.extend(f"{s.title}: {line}" for line in s.lines)
        return out

    def text(self) -> str:
        parts = [self.headline]
        for s in self.sections:
            if s.lines:
                parts.append(f"\n{s.title}:")
                parts.extend(f"• {line}" for line in s.lines)
        return "\n".join(parts)


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _pp(n: int, total: int) -> str:
    return f"{n / total * 100:.2f}pp" if total else "—"


def _who(source: str) -> str:
    if source.startswith("agent"):
        return "agents" if "chat" not in source else "agents (chat goal)"
    return {
        "chat": "you via chat",
        "ui": "you in the UI",
        "manual": "you",
        "human_approved": "approved by you",
        "dsp_auto": "DSP default",
        "manager": "manager",
        "supervisor_closeout": "supervisor",
    }.get(source, source)


def decisions(tw: StationOpsTwin, kinds: set[str]) -> list[str]:
    """Applied decisions in time order; repeated routine ones (sweeps,
    reminders, restages, ferry checks) are folded into one line each."""
    rows = [
        a for a in tw.applied if a["kind"] in kinds and not a["source"].startswith("disruption")
    ]
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for a in rows:
        by_kind[a["kind"]].append(a)
    out: list[tuple[float, str]] = []
    for kind, items in by_kind.items():
        done = [a for a in items if not a["effect"].startswith("no-op")]
        if len(done) >= 3 and kind in _ROUTINE:
            who = ", ".join(sorted({_who(a["source"]) for a in done}))
            targets = [a["target"] for a in done if a.get("target")]
            out.append(
                (
                    done[0]["minute"],
                    f"{done[0]['clock']}–{done[-1]['clock']} — {len(done)}× "
                    f"{_ROUTINE[kind]}"
                    + (f" ({', '.join(dict.fromkeys(targets))})" if targets else "")
                    + f" ({who})",
                )
            )
        else:
            out.extend(
                (a["minute"], f"{a['clock']} — {a['effect']} ({_who(a['source'])})") for a in items
            )
    return [t for _, t in sorted(out)]


_ROUTINE = {
    "direct_sweep": "sweeper sent to an aisle with a flagged bag",
    "notify_drivers": "driver reminders / reroutes",
    "restage_cart": "misstaged carts moved",
    "check_ferry": "extra ferry checks",
    "prioritize_route": "routes prioritised for pick",
    "notify_swipe_finish": "swipe-to-finish reminders",
    "request_replacement_van": "replacement vans requested",
    "offer_vet": "VET offer rounds",
}


def agent_reasoning(loop, metric_kinds: set[str], limit: int = 6) -> list[str]:
    """The planned (simulated-and-scored) decisions, with their expected gain."""
    out = []
    for a in loop.actions:
        if a.kind not in ("plan", "goal") or not a.applied:
            continue
        if not {i.kind for i in a.chosen_interventions} & metric_kinds:
            continue
        best = next((e for e in a.evaluations if e.name == a.chosen), None)
        gain = (
            f" — expected DEA {best.delta_dea_pp:+.2f}pp, OTD {best.delta_otd_pp:+.2f}pp over "
            f"{best.futures} belief future(s)"
            if best
            else ""
        )
        out.append(
            f"{a.clock} {a.agent_label}: '{a.chosen}' for {a.risk.risk_type.replace('_', ' ')}{gain}"
        )
    held = [
        a
        for a in loop.actions
        if a.status == "held" and a.risk.metric in ("dea", "otd", "timely_staged")
    ]
    if held:
        out.append(
            f"{len(held)} time(s) the agents considered acting and held back because no plan "
            "cleared the minimum simulated gain."
        )
    return out[-limit:] if len(out) > limit else out


# --- replay without decisions (simulated counterfactual) -----------------------------


def replay_inputs(tw: StationOpsTwin) -> tuple:
    """Config + only the *events* (injected disruptions) — none of the
    decisions. Scheduled disruptions and DSP defaults re-occur by themselves."""
    ivs = [
        Intervention(
            kind=a["kind"],
            amount=a["amount"],
            at_minute=a["minute"],
            target=a.get("target"),
            params=a.get("params") or {},
            source=a["source"],
        )
        for a in tw.applied
        if a["kind"] == "inject_disruption" and not a["source"].startswith("disruption")
    ]
    n_decisions = sum(
        1
        for a in tw.applied
        if a["kind"] != "inject_disruption"
        and a["source"] not in ("dsp_auto", "supervisor_closeout")
    )
    return tw.config, ivs, n_decisions


def replay_without_decisions(cfg, ivs) -> dict:
    s = run_station_day(cfg, ivs)
    return {
        "dea": s.metrics["dea"].value,
        "otd": s.metrics["otd"].value,
        "timely_staged": s.metrics["timely_staged"].value,
        "rolled_over": s.package_status["rolled_over"],
    }


def impact_lines(tw: StationOpsTwin, replay: dict | None, metric: str) -> list[str]:
    if replay is None:
        return ["Decision impact is measured once departures are complete."]
    snap = build_snapshot(tw, 0)
    actual = snap.metrics[metric].value
    base = replay[metric]
    if actual is None or base is None:
        return []
    d = (actual - base) * 100
    return [
        f"Replaying the same day without any of today's decisions gives {metric.upper()} "
        f"{_pct(base)} vs {_pct(actual)} actual — the decisions are worth {d:+.2f}pp "
        "(simulated counterfactual, same seed and disruptions)."
    ]


# --- DEA -------------------------------------------------------------------------------


def dea(tw: StationOpsTwin, loop, replay: dict | None) -> Analysis:  # noqa: C901
    snap = build_snapshot(tw, 0)
    m = snap.metrics
    c = tw.config
    today = [p for p in tw.pkgs if not p.carryover]
    n = len(today)
    final = tw.done
    val = m["dea"].value if final else m["dea_ceiling"].value
    target = c.targets.dea
    cats: Counter = Counter()
    late_trips: Counter = Counter()
    na_routes: Counter = Counter()
    cutoff = tw.cutoff
    for p in today:
        st = p.status
        if st == "rolled_over":
            if p.arrived_at is not None and p.arrived_at > cutoff:
                cats["arrived after pick start (late linehaul)"] += 1
                late_trips[p.trip] += 1
            elif p.inducted_at is None and p.problem:
                cats[f"stuck in problem solve ({p.problem.replace('_', ' ')})"] += 1
            elif p.inducted_at is None:
                cats["still waiting for induct at pick start"] += 1
            elif p.stowed_at is None:
                cats["inducted but not stowed by pick start (stow backlog / jackpot)"] += 1
            else:
                cats["stowed after its route was already picked"] += 1
        elif st == "next_cycle":
            if p.arrived_at is not None and p.arrived_at > cutoff:
                cats["arrived after pick start → received into tomorrow's cycle"] += 1
                late_trips[p.trip] += 1
            elif p.arrived_at is None and p.trip >= 0:
                cats["arrived after pick start → received into tomorrow's cycle"] += 1
                late_trips[p.trip] += 1
            else:
                cats["missed the cycle on the floor → changed to tomorrow's cycle"] += 1
        elif st == "held_wrong_cycle":
            cats["inducted after the cut without a cycle change → held (wrong cycle)"] += 1
        elif st in ("missed_induct", "pending_approval", "problem_solve", "jackpot") and final:
            cats[f"still in problem solve at day end ({st.replace('_', ' ')})"] += 1
        elif st == "pending_receive" and final:
            cats["linehaul never arrived"] += 1
        elif st == "left_behind":
            cats[f"left on the floor ({(p.left_reason or 'unknown').replace('_', ' ')})"] += 1
        elif st == "cluster_transfer":
            cats[
                f"found after its van left → cluster transfer ({(p.left_reason or '?').replace('_', ' ')})"
            ] += 1
        elif st == "held_damaged":
            cats["damaged beyond repair"] += 1
        elif st == "cancelled_inbound":
            cats["linehaul cancelled"] += 1
        elif p.attempted is False:
            cats["not attempted — route left too late to finish"] += 1
            na_routes[p.route] += 1
    misses = sum(cats.values())
    head = (
        f"DEA {'is' if final else 'can at best reach'} {_pct(val)} against a {_pct(target)} "
        f"target: {misses:,} of {n:,} promised packages {'missed' if final else 'are already lost'}"
        f" ({_pp(misses, n)})."
    )
    if val is not None and val >= target:
        head += " That meets target."
    elif cats:
        top, k = cats.most_common(1)[0]
        head += f" The main cause: {top} — {k:,} packages, {k / misses:.0%} of the misses."
    sections = [
        Section(
            title="Where the misses came from",
            lines=[f"{k}: {v:,} ({_pp(v, n)})" for k, v in cats.most_common()],
        )
    ]
    if late_trips:
        lines = []
        for t, k in late_trips.most_common(6):
            plan = c.linehauls[t]
            trip = tw.trips[t]
            learned = [r.reveal_minute for r in plan.revisions if r.delay_minutes > 0]
            lines.append(
                f"{plan.trip_id} from {plan.origin}"
                + (f" (ferry {plan.ferry_sailing})" if plan.via_ferry else "")
                + f": planned {clock(plan.planned_arrival_minute)}, arrived "
                f"{clock(trip.arrived_at / 60) if trip.arrived_at else '—'} "
                f"(+{plan.delay_minutes:.0f} min{', ' + plan.delay_reason if plan.delay_reason else ''})"
                f" → {k:,} packages rolled over"
                + (
                    f"; the delay was first learned at {clock(min(learned))}"
                    if learned and min(learned) > 0
                    else "; the delay was on the truckfile from the start of the shift"
                )
            )
        sections.append(Section(title="Late linehauls behind the rollover", lines=lines))
    cond = []
    lost = defaultdict(float)
    for ln, s, e, why in tw.line_down_windows:
        if s < cutoff:
            lost[(ln, why)] += (min(e, cutoff) - s) / 60
    for (ln, why), mins in sorted(lost.items()):
        cond.append(f"induct line L{ln} down {mins:.0f} min ({why})")
    for d in tw.disruptions_seen:
        if d["kind"] in ("scanner_degradation", "absenteeism", "volume_surge", "line_jam"):
            if d["kind"] == "line_jam":
                continue
            cond.append(
                f"{d['clock']} {d['kind'].replace('_', ' ')} "
                f"(magnitude {d['magnitude']:g}{', target ' + str(d['target']) if d['target'] else ''})"
            )
    wip = m["stow_wip_compliance"].value
    if wip is not None:
        cond.append(
            f"stow WIP inside the {c.settings.stow_wip_lower_min:g}–{c.settings.stow_wip_upper_min:g} min band "
            f"{_pct(wip)} of the time"
        )
    if tw.cutoff_extension_minutes:
        cond.append(
            f"pick start moved {tw.cutoff_extension_minutes:.0f} min later to {clock(tw.cutoff / 60)}"
        )
    absent = sum(1 for a in tw.assocs if not a.present and not a.vet)
    if absent:
        cond.append(f"{absent} rostered associate(s) absent")
    if cond:
        sections.append(Section(title="Conditions on the floor", lines=cond))
    if na_routes:
        sections.append(
            Section(
                title="Routes that left too late to attempt everything",
                lines=[
                    f"{tw.routes[r].route_id}: {k} not attempted (departed "
                    f"{clock(tw.routes[r].departed_at / 60)}, planned "
                    f"{clock(tw.routes[r].planned_depart / 60)})"
                    for r, k in na_routes.most_common(6)
                ],
            )
        )
    dec = decisions(tw, DEA_LEVERS)
    sections.append(
        Section(
            title="Decisions made to protect DEA",
            lines=dec[-14:] or ["No DEA-related actions were taken."],
        )
    )
    reasoning = agent_reasoning(loop, DEA_LEVERS)
    if reasoning:
        sections.append(Section(title="Why the agents chose them", lines=reasoning))
    sections.append(Section(title="Impact", lines=impact_lines(tw, replay, "dea") if final else []))
    return Analysis(
        topic="dea",
        title="Delivery estimate accuracy (DEA)",
        headline=head,
        sections=[s for s in sections if s.lines],
        sources=[
            Source(kind="metric", title=f"DEA definition ({METRIC_DEFINITIONS['dea']['status']})"),
            Source(kind="packages", title=f"{n:,} package records"),
            Source(kind="actions", title=f"{len(dec)} applied actions"),
        ],
    )


# --- OTD -------------------------------------------------------------------------------


def otd(tw: StationOpsTwin, loop, replay: dict | None) -> Analysis:  # noqa: C901
    snap = build_snapshot(tw, 0)
    m = snap.metrics
    tol = tw.config.dispatch.otd_tolerance_minutes * 60
    dep = [r for r in tw.routes if r.departed_at is not None]
    late = [r for r in dep if r.departed_at > r.planned_depart + tol]
    causes: Counter = Counter()
    lines = []
    for r in sorted(late, key=lambda r: -(r.departed_at - r.planned_depart))[:12]:
        d = tw.drivers[r.driver] if r.driver is not None else None
        why = []
        if d is not None:
            if d.vsa_result == "replaced":
                why.append(
                    f"van grounded at VSA ({d.vsa_defect}); {d.van_request} arrived "
                    f"{clock(d.van_eta / 60) if d.van_eta else '—'}"
                )
                causes["van grounded"] += 1
            if d.standby:
                why.append("original driver no-show / too late — standby driver sent")
                causes["driver no-show"] += 1
            elif d.arrived_at and d.arrived_at > r.planned_depart - LOAD_WINDOW_S:
                why.append(f"driver checked in {clock(d.arrived_at / 60)}")
                causes["driver late"] += 1
                if d.extra_travel_s:
                    why.append(f"traffic added {d.extra_travel_s / 60:.0f} min")
                    causes["traffic"] += 1
            if d.vsa_wait_s > 120:
                why.append(f"waited {d.vsa_wait_s / 60:.0f} min for a yard marshal")
                causes["VSA queue"] += 1
            if d.vsa_result == "minor_fixed":
                why.append(f"minor VSA defect fixed on site ({d.vsa_defect})")
                causes["VSA minor fix"] += 1
        if r.misstaged_since is not None:
            fixed = r.misstage_fixed_at or tw.env.now
            why.append(
                f"cart scanned to {r.misstaged_at or 'wrong location'} for "
                f"{(fixed - r.misstaged_since) / 60:.0f} min"
            )
            causes["misstaged cart"] += 1
        if r.staged_at and r.staged_at > r.planned_depart - LOAD_WINDOW_S:
            why.append(f"staged late at {clock(r.staged_at / 60)}")
            causes["late staging"] += 1
        lines.append(
            f"{r.route_id} ({r.dsp}) left {clock(r.departed_at / 60)}, "
            f"{(r.departed_at - r.planned_depart) / 60:.0f} min late: "
            + ("; ".join(why) or "late load")
        )
    head = (
        f"OTD is {_pct(m['otd'].value)} against the current plan ({_pct(m['otd_original_plan'].value)} "
        f"against the original wave plan): {len(late)} of {len(dep)} departed routes left late."
    )
    pending_late = [
        r
        for r in tw.routes
        if r.departed_at is None and not r.sidelined and tw.env.now > r.planned_depart
    ]
    if pending_late:
        head += f" {len(pending_late)} more route(s) are past their departure time."
    sections = [
        Section(
            title="Causes",
            lines=[f"{k}: {v} route(s)" for k, v in causes.most_common()],
        ),
        Section(title="Late routes", lines=lines),
    ]
    moved = [r for r in tw.routes if r.moved_waves]
    if moved:
        sections.append(
            Section(
                title="Routes moved to a later wave",
                lines=[
                    f"{r.route_id}: {clock(r.original_depart / 60)} → {clock(r.planned_depart / 60)}"
                    for r in moved[:8]
                ],
            )
        )
    dec = decisions(tw, OTD_LEVERS)
    sections.append(
        Section(title="Decisions made to protect OTD", lines=dec[-14:] or ["None yet."])
    )
    reasoning = agent_reasoning(loop, OTD_LEVERS)
    if reasoning:
        sections.append(Section(title="Why the agents chose them", lines=reasoning))
    if tw.done:
        sections.append(Section(title="Impact", lines=impact_lines(tw, replay, "otd")))
    return Analysis(
        topic="otd",
        title="On-time departure (OTD)",
        headline=head,
        sections=[s for s in sections if s.lines],
        sources=[
            Source(kind="routes", title=f"{len(dep)} departed routes"),
            Source(kind="drivers", title="driver check-ins and VSA records"),
            Source(kind="actions", title=f"{len(dec)} applied actions"),
        ],
    )


# --- trucks, ferries, truckfile -----------------------------------------------------------


def trucks(tw: StationOpsTwin, focus: str = "") -> Analysis:
    c = tw.config
    now = tw.now_minute
    st = Counter(t.status for t in tw.trips)
    rows, ferries, revs = [], [], []
    for i, plan in enumerate(c.linehauls):
        t = tw.trips[i]
        known = plan.known_delay(now)
        eta = plan.planned_arrival_minute + known
        line = (
            f"{plan.trip_id} {plan.origin}"
            + (f" ferry {plan.ferry_sailing}" if plan.via_ferry else " road")
            + f", {plan.volume:,} pkgs: "
        )
        if t.status == "cancelled":
            line += "cancelled"
        elif t.arrived_at is not None:
            line += (
                f"arrived {clock(t.arrived_at / 60)} (planned {clock(plan.planned_arrival_minute)}"
                + (f", +{plan.delay_minutes:.0f} min" if plan.delay_minutes else "")
                + f"), door {t.door}, unload #{t.sequence}"
            )
            if t.arrived_at > tw.cutoff:
                line += " — after pick start, volume rolled over"
        elif t.status == "in_yard":
            line += f"in the yard since {clock(t.yard_at / 60)}, waiting for a door"
        else:
            line += f"in transit, ETA {clock(eta)}" + (
                f" (+{known:.0f} min known)" if known else ""
            )
            if eta > tw.cutoff / 60:
                line += " — would arrive after pick start"
        rows.append(line)
        if plan.via_ferry:
            ferries.append(line)
        for r in plan.revisions:
            if r.reveal_minute <= now and r.reveal_minute > 0:
                revs.append(
                    f"{clock(r.reveal_minute)} {plan.trip_id}: ferry ETA revised to "
                    f"+{r.delay_minutes:.0f} min"
                )
    head = (
        f"Today: {st['arrived'] + st['unloading']} of {len(tw.trips)} linehauls arrived, "
        f"{st['in_yard']} in the yard, {st['in_transit']} in transit, {st['cancelled']} cancelled."
    )
    sections = []
    if "ferr" in focus:
        sections.append(Section(title="Ferry trips today", lines=ferries))
    sections.append(Section(title="Today's linehauls", lines=rows))
    if revs:
        sections.append(Section(title="Ferry ETA revisions learned today", lines=sorted(revs)))
    co = tw.closeout
    if co.started_at is not None:
        tf = co.trips
        delayed = [t for t in tf if t["known_delay"] or t["known_cancelled"] or t["added"]]
        pick = c.cycle.pick_start_minute
        head += (
            f" Tomorrow's truckfile ({co.tomorrow.isoformat()}) is "
            + (
                f"v{co.truckfile_version} (final published {clock(co.final_published_at)}"
                + (
                    f", revised {co.truckfile_version - 1} time(s) since"
                    if co.truckfile_version > 1
                    else ""
                )
                + ")"
                if co.final_published_at
                else "still a draft (final due " + clock(co.cfg.final_truckfile_minute) + ")"
            )
            + f" with {sum(1 for t in tf if t['known_volume'] > 0)} trips."
        )
        sections.append(
            Section(
                title="Tomorrow's trips with changes",
                lines=[
                    f"{t['trip_id']} {t['origin']}"
                    + (f" ferry {t['sailing']}" if t["via_ferry"] else "")
                    + (" (added)" if t["added"] else "")
                    + f": {t['known_volume']:,} pkgs, "
                    + (
                        "cancelled"
                        if t["known_cancelled"]
                        else f"ETA {clock(t['planned_arrival'] + t['known_delay'])} "
                        f"(+{t['known_delay']:.0f} min)"
                        + (
                            " — after pick start"
                            if t["planned_arrival"] + t["known_delay"] > pick - 60
                            else ""
                        )
                    )
                    for t in delayed
                ]
                or ["No changes to tomorrow's trips so far."],
            )
        )
        if co.truckfile_log:
            sections.append(
                Section(
                    title="Truckfile revision log",
                    lines=[
                        f"{x['clock']} {x['trip_id']}: {x['field']} {x['before']} → {x['after']} "
                        f"({x['why']}; via {x['how']}"
                        + (f", after final → v{x['version']}" if x["after_final"] else "")
                        + ")"
                        for x in co.truckfile_log[-10:]
                    ],
                )
            )
        if co.ferry_checks:
            last = co.ferry_checks[-1]
            sections.append(
                Section(
                    title="Ferry checks",
                    lines=[
                        f"{len(co.ferry_checks)} checks so far; last at {last['clock']} "
                        f"({last['changes']} change(s))"
                    ],
                )
            )
        if co.gtdr:
            sections.append(
                Section(
                    title="GTDR (Global Trailer Dock and Release)",
                    lines=[
                        f"{g['gtdr_id']} {g['direction'].replace('_', ' ')} {g['trailer']} "
                        f"{g['place']}: scheduled {g['scheduled']}, actual {g['actual']} "
                        f"(+{g['delay_minutes']} min), {g['units']} units — {g['status']}"
                        for g in co.gtdr
                    ],
                )
            )
    if "gtdr" in focus:
        sections.sort(key=lambda x: not x.title.startswith("GTDR"))
    return Analysis(
        topic="trucks",
        title="Trucks, ferries & truckfile",
        headline=head,
        sections=sections,
        sources=[
            Source(kind="truckfile", title=f"today's truckfile ({len(tw.trips)} trips)"),
            Source(kind="truckfile", title="tomorrow's truckfile & revision log"),
            Source(kind="gtdr", title=f"{len(co.gtdr)} GTDR record(s)"),
        ],
    )


# --- labor: associates, VET / VTO -----------------------------------------------------------


def labor(tw: StationOpsTwin) -> Analysis:
    now = tw.env.now
    present = [a for a in tw.assocs if a.present]
    roles = Counter(a.role for a in present if a.task != "off_shift")
    vet = [a for a in tw.assocs if a.vet]
    absent = [a for a in tw.assocs if not a.present and not a.vet]
    head = (
        f"Today: {len([a for a in tw.assocs if not a.vet])} rostered, {len(absent)} absent, "
        f"{len(vet)} called in on VET (flex pool left {tw.flex_remaining})."
    )
    sections = [
        Section(
            title="On the floor now",
            lines=[
                ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in roles.items())
                or "nobody — shift over"
            ],
        )
    ]
    calls = decisions(tw, {"add_stowers", "add_pickers", "move_associates", "open_induct_line"})
    if calls:
        sections.append(Section(title="Labor moves and VET call-ins today", lines=calls))
    if vet:
        by = Counter(a.home_role for a in vet)
        sections.append(
            Section(
                title="VET associates today",
                lines=[f"{v} {k}" for k, v in by.items()]
                + [f"first arrived {clock(min(a.shift_start for a in vet) / 60)}"],
            )
        )
    idle = [
        f"{a.login} ({a.role}, {(now - a.idle_since) / 60:.0f} min)"
        for a in present
        if a.task == "idle" and a.idle_since and now - a.idle_since > 600
    ]
    if idle:
        sections.append(Section(title="Idle more than 10 min", lines=idle[:8]))
    co = tw.closeout
    if co.started_at is not None:
        opps = co.opportunities.items
        for kind in ("VET", "VTO"):
            os_ = [o for o in opps if o["type"] == kind]
            if not os_:
                continue
            src = Counter(_who(o["source"]) for o in os_)
            lines = [
                f"{len(os_)} opportunit{'y' if len(os_) == 1 else 'ies'} posted "
                f"({', '.join(f'{v} by {k}' for k, v in src.items())}): "
                f"{sum(o['headcount'] for o in os_)} HC asked, "
                f"{sum(len(o['submitted']) for o in os_)} submitted, "
                f"{sum(len(o['accepted']) for o in os_)} accepted"
            ]
            for o in os_[:6]:
                lines.append(
                    f"{o['id']} {o['frame']} ({o['time_frame']}): posted {o['posted_clock']}, window "
                    f"{'open until' if o['status'] == 'open' else 'closed'} {o['window_close_clock']}"
                    f" — {len(o['submitted'])} submitted / {len(o['accepted'])} accepted of {o['headcount']}"
                )
            acc = [a["login"] for o in os_ for a in o["accepted"]]
            lines.append("accepted: " + (", ".join(acc[:12]) or "none"))
            sections.append(Section(title=f"Tomorrow — {kind} opportunities", lines=lines))
        recs = co.opportunities.recommendations()
        if recs:
            sections.append(
                Section(
                    title="Tomorrow — still to post (assuming no more acceptance)",
                    lines=[
                        f"{r['type']} {r['headcount']} HC for {r['frame']} ({r['time_frame']})"
                        for r in recs
                    ],
                )
            )
        sh = co.expected_show()
        plan = co.labor_plan()
        t = plan["totals"]
        sections.append(
            Section(
                title="Tomorrow — headcount",
                lines=[
                    f"show hours {t['show_hours']} vs needed hours {t['needed_hours']}; planned TPH "
                    f"{t['tph_with_indirect']} (with indirect) / {t['tph_without_indirect']} (without)",
                    f"expected show {sh['expected']}: {sh['scheduled']} scheduled, "
                    f"{sh['vet_accepted']} VET accepted, {sh['vto_accepted']} VTO accepted, "
                    f"{sh['called_out']} call-out(s), {sh['pending_offers']} window(s) open",
                ]
                + [
                    f"{w['name']} {w['window']}: {w['scheduled']} scheduled × {w['attendance']:.0%} = "
                    f"{w['expected_headcount']} expected (peak need {w['needed_peak']})"
                    for w in plan["work_groups"]
                    if w["scheduled"]
                ]
                + [f"{x['clock']} {x['login']} called out" for x in co.callouts],
            )
        )
    return Analysis(
        topic="labor",
        title="Associates, VET & VTO",
        headline=head,
        sections=sections,
        sources=[
            Source(kind="associates", title=f"{len(tw.assocs)} associate records"),
            Source(kind="offers", title=f"{len(co.opportunities.items)} VET/VTO opportunities"),
        ],
    )


# --- tomorrow ------------------------------------------------------------------------------


def tomorrow(tw: StationOpsTwin) -> Analysis:
    co = tw.closeout
    if co.started_at is None:
        return Analysis(
            topic="tomorrow",
            title="Tomorrow",
            headline="Close-out starts after the last departure — tomorrow's truckfile is a draft until "
            f"{clock(co.cfg.final_truckfile_minute)} and the plan is built after that.",
        )
    o = co.known_ofd()
    n = co.needs(o["ofd_volume"])
    sh = co.expected_show()
    head = (
        f"Tomorrow ({co.tomorrow.isoformat()}): predicted OFD volume {o['ofd_volume']:,} → "
        f"{n['routes']} routes, SPR {n['spr']}, TPH {n['tph']:,}; need {n['headcount']} associates, "
        f"expected {sh['expected']}."
    )
    sections = [
        Section(
            title="Volume",
            lines=[
                f"linehaul arriving before pick start: {o['linehaul_in_time']:,}",
                f"carry-over: {o['carryover']:,} (rollover {o['rollover']:,}, cluster transfer "
                f"{o['cluster_transfer']:,}, re-attempts {o['reattempt']:,}, late trailer {o['late_trailer']:,})",
                f"at risk of arriving after pick start (not counted): {o['linehaul_at_risk']:,}",
                f"cancelled: {o['cancelled']:,}",
            ],
        )
    ]
    if co.plan:
        p = co.plan
        sections.append(
            Section(
                title="Plan",
                lines=[
                    f"v{p['version']} built {p['clock']} on truckfile v{p['truckfile_version']}"
                    + (
                        f" — truckfile is now v{co.truckfile_version}, re-plan needed"
                        if p["truckfile_version"] != co.truckfile_version
                        else ""
                    ),
                    f"{len(p['zones'])} stow zones; rotation compliance {p['rotation_compliance']:.0%} "
                    f"({p['rotation_violations']} violation(s))",
                ]
                + [
                    f"v{h['version']} {h['clock']} ({h['label']}): OFD {h['ofd_volume']:,}, gap {h['gap']:+}"
                    for h in co.plan_history
                ],
            )
        )
    if co.readiness:
        r = co.readiness
        sections.append(
            Section(
                title="Readiness (against the full truckfile truth)",
                lines=[
                    f"true OFD {r['true_ofd_volume']:,} vs planned {r['planned_ofd_volume']:,}",
                    f"staffing gap {r['staffing_gap']:+}; unrevealed revisions {r['unrevealed_revisions']}",
                ],
            )
        )
    dec = decisions(tw, PLAN_LEVERS)
    if dec:
        sections.append(Section(title="Planning decisions", lines=dec[-10:]))
    return Analysis(
        topic="tomorrow",
        title="Tomorrow's volume & plan",
        headline=head,
        sections=sections,
        sources=[
            Source(kind="truckfile", title=f"tomorrow's truckfile v{co.truckfile_version}"),
            Source(kind="plan", title=f"plan v{co.plan['version'] if co.plan else 0}"),
        ],
    )


# --- decisions & whole shift -------------------------------------------------------------------


def decisions_summary(tw: StationOpsTwin, loop) -> Analysis:
    applied = [a for a in loop.actions if a.applied]
    by_agent = Counter(a.agent_label for a in applied)
    human = [a for a in tw.applied if a["source"] in ("chat", "ui", "manual", "human_approved")]
    pending = [a for a in loop.actions if a.status == "pending"]
    head = (
        f"Agents ({loop.mode}) applied {len(applied)} action(s) today; you applied {len(human)}; "
        f"{len(pending)} recommendation(s) await approval."
    )
    sections = [
        Section(title="By agent", lines=[f"{k}: {v}" for k, v in by_agent.most_common()]),
        Section(
            title="Planned decisions (simulated before acting)",
            lines=agent_reasoning(loop, DEA_LEVERS | OTD_LEVERS | PLAN_LEVERS, limit=10),
        ),
        Section(
            title="Recent actions",
            lines=[
                f"{a['clock']} {a['effect']} ({_who(a['source'])})"
                for a in tw.applied[-12:]
                if not a["source"].startswith("disruption")
            ],
        ),
    ]
    if human:
        sections.append(
            Section(title="Yours", lines=[f"{a['clock']} {a['effect']}" for a in human[-8:]])
        )
    return Analysis(
        topic="decisions",
        title="Decisions",
        headline=head,
        sections=[s for s in sections if s.lines],
        sources=[Source(kind="actions", title=f"{len(loop.actions)} agent records")],
    )


def shift(tw: StationOpsTwin, loop) -> Analysis:
    snap = build_snapshot(tw, 0)
    m = snap.metrics
    c = tw.config
    arrived = [t.arrived_at for t in tw.trips if t.arrived_at is not None]
    dep = [r.departed_at for r in tw.routes if r.departed_at is not None]
    timeline = []
    if arrived:
        timeline.append(f"{clock(min(arrived) / 60)} first linehaul at a door")
    if tw.pick_started:
        timeline.append(
            f"{clock(tw.cutoff / 60)} pick started"
            + (
                f" (moved {tw.cutoff_extension_minutes:.0f} min)"
                if tw.cutoff_extension_minutes
                else ""
            )
        )
    if dep:
        timeline.append(f"{clock(min(dep) / 60)} first route departed")
    if tw.departures_done_at:
        timeline.append(f"{clock(tw.departures_done_at / 60)} last route departed — associates off")
    if tw.closeout.final_published_at:
        timeline.append(
            f"{clock(tw.closeout.final_published_at)} tomorrow's final truckfile published"
        )
    if tw.closeout.finished_at:
        timeline.append(f"{clock(tw.closeout.finished_at)} close-out complete")
    dis = [
        f"{d['clock']} {d['kind'].replace('_', ' ')}" + (f" ({d['target']})" if d["target"] else "")
        for d in tw.disruptions_seen
    ]
    applied = [a for a in loop.actions if a.applied]
    head = (
        f"Day {c.day} ({c.ofd_date.isoformat()}, {c.name.replace('_', ' ')}), now {snap.clock} — "
        f"{snap.phase.replace('_', ' ')}. DEA {_pct(m['dea'].value if tw.done else m['dea_ceiling'].value)}"
        f"{'' if tw.done else ' (ceiling)'}, OTD {_pct(m['otd'].value)}, sort compliance "
        f"{_pct(m['sort_compliance'].value)}, timely staged {_pct(m['timely_staged'].value)}, "
        f"scan compliance {_pct(m['scan_compliance'].value)}."
    )
    sections = [
        Section(title="Timeline", lines=timeline),
        Section(title="What happened (disruptions)", lines=dis or ["a quiet day"]),
        Section(
            title="Floor and yard exceptions",
            lines=[
                f"{tw.counters['misstaged']} wrong staging scan(s), {tw.counters['vsa_grounded']} van(s) "
                f"grounded, {tw.counters['vsa_minor']} fixed on site",
                f"{tw.counters['sweep_staged']} left-behind package(s) recovered to carts by the sweep, "
                f"{tw.counters['cluster_transfer']} cluster-transferred",
                f"{snap.package_status['rolled_over']:,} rolled over",
            ],
        ),
        Section(
            title="Agents",
            lines=[f"{len(applied)} action(s) applied in {loop.mode} mode"]
            + [f"{k}: {v}" for k, v in Counter(a.agent_label for a in applied).most_common()],
        ),
    ]
    return Analysis(
        topic="shift",
        title="Shift summary",
        headline=head,
        sections=sections,
        sources=[
            Source(kind="metric", title="live metrics"),
            Source(kind="events", title="event log"),
        ],
    )
