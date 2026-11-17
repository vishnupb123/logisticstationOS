"""Station Assistant v2 analyses (HANDOFF_V2 §10.1).

Each topic follows the answer contract: headline → what happened (numbers)
→ why (causes, ranked) → what was done (decisions with who/when) → what to
do now → sources. Deterministic and authoritative; the LLM may only
summarise these facts (ADR-0013 grounding check unchanged).
"""

from __future__ import annotations

import re
from collections import Counter

from app.runtime.explain import Analysis, Section, Source, decisions
from app.simulation.station_ops import labor_plan as lp
from app.simulation.station_ops import metrics as engine
from app.simulation.station_ops import status as st
from app.simulation.station_ops.model import StationOpsTwin, clock
from app.simulation.station_ops.views_v2 import plan_vs_actual, stow_v2


def _todo(tw: StationOpsTwin, kinds: set[str]) -> list[str]:
    return [
        f"{w['id']} {w['title']} (owner {w['owner']}, expires {w['expires_clock']})"
        for w in tw.work_items.open_items()
        if w["kind"] in kinds or not kinds
    ][:6]


def cycles(tw: StationOpsTwin) -> Analysis:
    c = tw.config
    on_floor = sum(1 for p in tw.pkgs if p.status == "rolled_over" and p.arrived_at is not None)
    not_arrived = sum(1 for p in tw.pkgs if p.status == "rolled_over" and p.arrived_at is None)
    by_reason = Counter(
        "inducted after the cut"
        if p.inducted_at is not None
        else "still at problem solve"
        if p.problem
        else "waiting for induct"
        for p in tw.pkgs
        if p.status == "rolled_over" and p.arrived_at is not None
    )
    k = tw.counters
    if not tw.pick_started:
        head = (
            f"Pick for {c.cycle.name} starts at {clock(tw.cutoff / 60)}; induct is open "
            f"(belt run time left {tw.belt_run_minutes(tw.now_minute, tw.cutoff / 60) / 60:.1f} h)."
        )
    else:
        head = (
            f"Pick started for {c.cycle.name} at {clock(tw.cutoff / 60)} and blocked induct: "
            f"{on_floor + k['next_cycle']} package(s) on the floor missed the cycle, "
            f"{k['next_cycle']} moved to tomorrow's cycle cleanly, {k['held_wrong_cycle']} held as wrong-cycle."
        )
    sections = [
        Section(
            title="What happened",
            lines=[
                f"still on the floor (rolled over): {on_floor} — "
                + (", ".join(f"{v} {r}" for r, v in by_reason.items()) or "none"),
                f"arriving after the cut (not yet on site): {not_arrived}",
                f"force-induct sent {k['force_staged']} late package(s) straight to their route's cart",
                f"next cycle (changed): {k['next_cycle']}; wrong-cycle holds: {k['held_wrong_cycle']}",
            ],
        ),
        Section(
            title="Cycle actions",
            lines=[
                f"{x['clock']} {x['action'].replace('_', ' ')}"
                + (f" — {x.get('packages', '')} pkgs" if "packages" in x else "")
                + (f" ({x['minutes']:.0f} min)" if "minutes" in x else "")
                + (f" ({x['hours']:.0f} h)" if "hours" in x else "")
                for x in tw.cycle_changes
            ]
            or ["none"],
        ),
    ]
    dec = decisions(tw, {"force_induct", "change_cycle", "enable_cycle", "extend_cutoff"})
    if dec:
        sections.append(Section(title="Decisions (who / when / effect)", lines=dec))
    todo = _todo(tw, {"cycle_pick_started"})
    if todo:
        sections.append(Section(title="What to do now", lines=todo))
    return Analysis(
        topic="cycles",
        title="Cycle & pick start",
        headline=head,
        sections=sections,
        sources=[Source(kind="cycle", title=f"{len(tw.cycle_changes)} cycle action(s)")],
    )


def quality(tw: StationOpsTwin) -> Analysis:
    m = engine.compute(tw)
    q = m["quality"]["inputs"]
    top = q["top_impact"]
    lost = m["lost_hours"]
    dpmo = m["induct_downtime_dpmo"]
    rows = []
    for r in q["by_line"]:
        if not r["attempts"]:
            continue
        rows.append(
            f"{r['line']} ({'automated' if r['automated'] else 'manual'}): {r['attempts']} attempts, no-read "
            f"{(r['no_read'] or 0):.2%}, multi-read {(r['multi_read'] or 0):.2%}, misapplied label "
            f"{(r['misapplied_label'] or 0):.2%}, lost {lost['inputs']['by_line'].get(r['line'], 0)} h, "
            f"downtime DPMO {dpmo['inputs']['by_line'].get(r['line']) or '—'}"
        )
    worst_lost = lost["inputs"]["top_3"][0] if lost["inputs"]["top_3"] else None
    head = (
        f"Top quality issue: {top['issue'].replace('_', ' ')} on {top['line']} ({top['rate']:.2%})."
        if top
        else "No induct quality issues recorded yet."
    )
    if worst_lost and worst_lost[1] > 0:
        head += f" Most lost hours: {worst_lost[0]} ({worst_lost[1]} h of belt gaps)."
    sections = [
        Section(title="By line", lines=rows or ["no induct activity yet"]),
        Section(
            title="Station totals (documented definitions)",
            lines=[
                f"lost hours {lost['value']} h from {lost['inputs']['stops']} belt gaps of 20–120 s",
                f"induct downtime DPMO {dpmo['value']} (stops ÷ inducted × 1,000,000)",
                f"missed induct {m['missed_induct']['value']}; misdivert DPMO {m['misdivert_dpmo']['value']} "
                f"({m['misdivert_dpmo']['inputs']['by_kind']})",
                f"network missorts {m['network_missorts']['value']} ({m['network_missorts']['inputs']['by_reason']})",
            ],
        ),
    ]
    dec = decisions(
        tw, {"open_induct_line", "move_associates", "rebalance_finger", "approve_damaged"}
    )
    if dec:
        sections.append(Section(title="What was done", lines=dec))
    return Analysis(
        topic="quality",
        title="Induct quality & downtime by line",
        headline=head,
        sections=sections,
        sources=[Source(kind="metric", title="Quality metrics, lost hours, DPMO")],
    )


def stow_wip(tw: StationOpsTwin, text: str = "") -> Analysis:
    m = engine.compute(tw)
    w, comp = m["stow_wip_minutes"], m["stow_wip_compliance"]
    s = tw.config.settings
    ints = comp["inputs"]["timeline"]
    at = re.search(r"\b(\d{1,2}):?(\d{2})\b", text)
    focus = None
    if at:
        target = int(at.group(1)) * 60 + int(at.group(2))
        focus = min(ints, key=lambda x: abs(x["end"] - target), default=None) if ints else None
    out_band = [x for x in ints if not x["ok"]]
    head = (
        f"Stow WIP is {w['value']} min (INC {w['inputs']['inc_pending_stow']} ÷ Stow FPH {w['inputs']['stow_fph']} × 60) "
        f"against the {s.stow_wip_lower_min:g}–{s.stow_wip_upper_min:g} min band; compliance "
        f"{(comp['value'] or 0):.0%} over {comp['inputs']['intervals']} 15-minute intervals "
        f"(target {s.stow_wip_compliance_target:.0%})."
    )
    lines = []
    if focus:
        lines.append(
            f"interval ending {focus['clock']}: average WIP {focus['wip']} min — "
            + ("within band" if focus["ok"] else "out of band")
        )
    lines += [
        f"{x['clock']}: {x['wip']} min {'(above)' if x['wip'] > s.stow_wip_upper_min else '(below)'}"
        for x in out_band[:10]
    ]
    why = []
    hi = [x for x in out_band if x["wip"] > s.stow_wip_upper_min]
    lo = [x for x in out_band if x["wip"] < s.stow_wip_lower_min]
    if hi:
        why.append(
            f"{len(hi)} interval(s) above band: stow capacity below induct (or no stow flow right after "
            "sort start / a break) — buffered work piles up"
        )
    if lo:
        why.append(
            f"{len(lo)} interval(s) below band: inbound running dry or more stowers than the flow needs"
        )
    sections = [
        Section(title="Out-of-band intervals", lines=lines or ["none"]),
        Section(title="Why", lines=why or ["WIP stayed inside the band"]),
    ]
    dec = decisions(tw, {"add_stowers", "move_associates", "rebalance_finger"})
    if dec:
        sections.append(Section(title="What was done", lines=dec))
    return Analysis(
        topic="stow_wip",
        title="Stow WIP & compliance",
        headline=head,
        sections=sections,
        sources=[Source(kind="metric", title="Stow WIP (documented formula)")],
    )


def receive(tw: StationOpsTwin) -> Analysis:
    arrived = [p for p in tw.pkgs if p.arrived_at is not None]
    unplanned = [p for p in arrived if not p.planned]
    expected = sum(
        t.volume * t.unplanned_share
        for i, t in enumerate(tw.config.linehauls)
        if tw.trips[i].yard_at is not None
    )
    by_trip = Counter(tw.config.linehauls[p.trip].trip_id for p in unplanned if p.trip >= 0)
    surge = sum(1 for p in unplanned if p.trip < 0)
    head = (
        f"{len(unplanned):,} unplanned package(s) have arrived ({len(unplanned) / max(1, len(arrived)):.0%} of "
        f"{len(arrived):,} arrived) vs ~{expected:,.0f} expected from the manifests"
        + (f"; {surge} came in an unplanned surge." if surge else ".")
    )
    planned = [p for p in arrived if p.planned]
    sections = [
        Section(
            title="Planned vs. unplanned",
            lines=[
                f"planned arrived {len(planned):,}, inducted {sum(1 for p in planned if p.inducted_at):,}, stowed {sum(1 for p in planned if p.stowed_at):,}",
                f"unplanned arrived {len(unplanned):,}, inducted {sum(1 for p in unplanned if p.inducted_at):,}, stowed {sum(1 for p in unplanned if p.stowed_at):,}",
            ],
        ),
        Section(
            title="Top trips by unplanned volume",
            lines=[f"{t}: {n}" for t, n in by_trip.most_common(5)] or ["none"],
        ),
    ]
    return Analysis(
        topic="receive",
        title="Receive: planned vs. unplanned",
        headline=head,
        sections=sections,
        sources=[Source(kind="linehaul", title=f"{len(tw.config.linehauls)} trips")],
    )


def containers(tw: StationOpsTwin) -> Analysis:
    rows = []
    for c in tw.containers:
        pend = sum(
            1
            for i in c["pkgs"]
            if tw.pkgs[i].status in ("pending_receive", "pending_induct", "inducting")
        )
        if pend:
            rows.append((tw.config.linehauls[c["trip"]].trip_id, c, pend))
    unloaded = [r for r in rows if r[1]["unloaded_at"] is not None]
    head = (
        f"{len(rows)} container(s) still pending induct ({sum(r[2] for r in rows):,} packages); "
        f"{len(unloaded)} of them are already unloaded on the dock."
    )
    lines = [
        f"{t} {c['type'].lower()} {c['id']}: {p}/{len(c['pkgs'])} pending"
        + (
            f", unloaded {clock(c['unloaded_at'] / 60)}"
            if c["unloaded_at"] is not None
            else ", still on the trailer"
        )
        for t, c, p in sorted(rows, key=lambda r: (r[1]["unloaded_at"] is None, -r[2]))[:12]
    ]
    return Analysis(
        topic="containers",
        title="Containers pending induct",
        headline=head,
        sections=[Section(title="Containers", lines=lines or ["none pending"])],
        sources=[Source(kind="container", title=f"{len(tw.containers)} containers")],
    )


def ageing(tw: StationOpsTwin) -> Analysis:
    from app.simulation.station_ops.views_v2 import ageing_v2

    a = ageing_v2(tw)
    old = [
        (g["group"], r["status"], r["2 days"] + r["3 days"] + r["4+ days"])
        for g in a["forward"]
        for r in g["rows"]
    ]
    old = [x for x in old if x[2]]
    head = (
        f"{sum(x[2] for x in old)} package(s) have been in a status for 2+ days; "
        f"{len(a['missing_packages'])} marked missing, {len(a['lost_packages'])} marked lost."
    )
    sc = [
        f"{s['kind'].replace('_', '-')} scrub at {clock(s['minute'])}: {s['resolved']} resolved"
        for s in a["scrubs"]
    ]
    return Analysis(
        topic="ageing",
        title="Ageing",
        headline=head,
        sections=[
            Section(
                title="2+ days by status",
                lines=[f"{g} / {s}: {n}" for g, s, n in sorted(old, key=lambda x: -x[2])]
                or ["none"],
            ),
            Section(title="Scrubs", lines=sc or ["no scrub run yet today"]),
            Section(
                title="What to do now",
                lines=_todo(
                    tw, {"review_missing", "review_lost", "in_station_scrub", "on_road_scrub"}
                )
                or ["nothing open"],
            ),
        ],
        sources=[Source(kind="ageing", title="Ageing (forward + reverse)")],
    )


def labor_plan(tw: StationOpsTwin, text: str = "") -> Analysis:
    co = tw.closeout
    tomorrow = co.started_at is not None
    plan = (
        co.labor_plan()
        if tomorrow
        else lp.build_plan(tw.config, tw.config.planned_volume, pick_start=tw.cutoff / 60)
    )
    hrs = re.findall(r"\b(\d{1,2}):?(\d{2})\b", text)
    sel = list(range(len(plan["hour_minutes"])))
    if len(hrs) >= 2:
        a = int(hrs[0][0]) * 60 + int(hrs[0][1])
        b = int(hrs[1][0]) * 60 + int(hrs[1][1])
        sel = [i for i, h in enumerate(plan["hour_minutes"]) if a <= h < b] or sel
    lines = [
        f"{plan['hours'][i]}: need {plan['needed_by_hour'][i]} HC, expected {plan['available_by_hour'][i]} "
        f"({'short ' + str(plan['gap_by_hour'][i]) if plan['gap_by_hour'][i] > 0 else 'covered'})"
        for i in sel
    ]
    short = [i for i in sel if plan["gap_by_hour"][i] > 0.5]
    t = plan["totals"]
    head = (
        f"{'Tomorrow' if tomorrow else 'Today'}: show {t['show_hours']} h vs needed {t['needed_hours']} h; "
        + (
            f"short in {len(short)} of {len(sel)} hour(s) asked about."
            if short
            else f"covered in all {len(sel)} hour(s) asked about."
        )
    )
    sections = [Section(title="By hour", lines=lines)]
    if tomorrow:
        sections.append(
            Section(
                title="Opportunities",
                lines=[
                    f"{o['id']} {o['type']} {o['frame']}: {len(o['submitted'])} submitted / {len(o['accepted'])} accepted of {o['headcount']} ({o['status']})"
                    for o in co.opportunities.items
                ]
                or ["none posted"],
            )
        )
        recs = co.opportunities.recommendations()
        sections.append(
            Section(
                title="Still to post",
                lines=[f"{r['type']} {r['headcount']} HC {r['frame']}" for r in recs]
                or ["nothing"],
            )
        )
    return Analysis(
        topic="labor_plan",
        title="Labor plan by hour",
        headline=head,
        sections=sections,
        sources=[Source(kind="plan", title="Labor plan v2 (proposed rates)")],
    )


def rotation(tw: StationOpsTwin, text: str = "") -> Analysis:
    co = tw.closeout
    if not co.rotation:
        return Analysis(
            topic="rotation",
            title="Shift rotation",
            headline="Tomorrow's rotation hasn't run yet — it runs with the plan (18:00) and can be re-run.",
        )
    path = next(
        (
            p
            for p in (
                "stow",
                "pick",
                "induct",
                "container_building",
                "auto_induct_loader",
                "sort_problem_solve",
            )
            if p.replace("_", " ") in text or p in text
        ),
        None,
    )
    rows = co.rotation
    blocked = (
        [r for r in rows if path and path in r["disallowed_paths"]]
        if path
        else [r for r in rows if r["disallowed_paths"]]
    )
    untrained = [r for r in rows if path and path not in r["trained_paths"]] if path else []
    st_ = co.rotation_stats
    head = (
        f"Rotation compliance {st_.get('compliance', 0):.0%} ({st_.get('filled', 0)}/{st_.get('slots', 0)} slots filled, "
        f"{st_.get('unfilled', 0)} unfilled, solver {st_.get('solver')}). "
        + (
            f"{len(blocked)} associate(s) can't do {path} tomorrow (heavy-path rule), {len(untrained)} aren't trained on it."
            if path
            else f"{len(blocked)} associate(s) have disallowed paths."
        )
    )
    pri = Counter(r["rotation_priority"] for r in rows)
    return Analysis(
        topic="rotation",
        title="Shift rotation",
        headline=head,
        sections=[
            Section(
                title="Why (rule)",
                lines=[
                    f"a heavy path on ≥{tw.config.labor_plan.heavy_days_disallow} of the last 3 days is disallowed (proposed)",
                    f"priority: {pri['High']} High, {pri['Low']} Low, {pri['None']} None",
                ],
            ),
            Section(
                title="Disallowed (counts by path)",
                lines=[
                    f"{p}: {n}"
                    for p, n in Counter(
                        x for r in rows for x in r["disallowed_paths"]
                    ).most_common()
                ]
                or ["none"],
            ),
        ],
        sources=[Source(kind="rotation", title=f"{len(rows)} associates")],
    )


def work_items(tw: StationOpsTwin) -> Analysis:
    s = tw.work_items.summary()
    expired = [w for w in tw.work_items.items if w["state"] == "expired"]
    by_cat = Counter(w["category"] for w in expired)
    head = (
        f"{s['expired_today']} work item(s) expired today, {s['completed_today']} completed, "
        f"{s['pending']} pending ({s['high_priority']} high priority)."
    )
    return Analysis(
        topic="work_items",
        title="Work items",
        headline=head,
        sections=[
            Section(
                title="Expired by category",
                lines=[f"{c}: {n}" for c, n in by_cat.most_common()] or ["none"],
            ),
            Section(
                title="Expired items",
                lines=[
                    f"{w['created_clock']} {w['title']} (expired {w['expires_clock']})"
                    for w in expired[-10:]
                ]
                or ["none"],
            ),
            Section(title="Pending now", lines=_todo(tw, set()) or ["nothing pending"]),
        ],
        sources=[Source(kind="work_items", title=f"{len(tw.work_items.items)} items")],
    )


def plan_actual(tw: StationOpsTwin, text: str = "") -> Analysis:
    pva = plan_vs_actual(tw)
    rows = [r for r in pva["intervals"] if r["induct_actual"] is not None]
    at = re.search(r"\b(\d{1,2}):?(\d{2})\b", text)
    if at and rows:
        target = int(at.group(1)) * 60 + int(at.group(2))
        hour = [r for r in rows if target <= r["start"] < target + 60] or [
            min(rows, key=lambda r: abs(r["start"] - target))
        ]
    else:
        hour = rows[-4:]

    def tot(key):
        return sum((r[key] or 0) for r in hour)

    head = (
        f"{hour[0]['label'].split('–')[0]}–{hour[-1]['label'].split('–')[1]}: induct {tot('induct_actual'):,.0f} vs plan "
        f"{tot('induct_planned'):,.0f}, stow {tot('stow_actual'):,.0f} vs {tot('stow_planned'):,.0f}, receive "
        f"{tot('receive_actual'):,.0f} vs {tot('receive_planned'):,.0f}."
        if hour
        else "No actuals yet."
    )
    return Analysis(
        topic="plan_actual",
        title="Plan vs. actual",
        headline=head,
        sections=[
            Section(
                title="15-minute intervals",
                lines=[
                    f"{r['label']}: induct {r['induct_actual']} / {r['induct_planned']}, stow {r['stow_actual']} / {r['stow_planned']}, "
                    f"pick {r['pick_actual']} / {r['pick_planned']}"
                    for r in hour
                ],
            ),
        ],
        sources=[Source(kind="plan", title="Plan vs. actual grid")],
    )


def fingers(tw: StationOpsTwin) -> Analysis:
    v = stow_v2(tw)
    head = "; ".join(
        f"{f['machine']} {f['buffer']}/{f['bay_capacity']} in buffer, {f['full_bay_events']} full-bay diversion(s)"
        for f in v["fingers"]
    )
    return Analysis(
        topic="fingers",
        title="Auto-divert fingers",
        headline=head + ".",
        sections=[
            Section(
                title="Clusters",
                lines=[
                    f"{c['cluster']}: stowed {c['stowed']}/{c['planned']} ({(c['stow_plan'] or 0):.0%}), buffered {c['stow_buffered']}, jackpot {c['jackpot_buffered']}, {c['active_stowers']} stowers"
                    for c in v["clusters"]
                ],
            ),
        ],
        sources=[Source(kind="finger", title="Stow buffer by finger")],
    )


def status_counts(tw: StationOpsTwin) -> dict[str, int]:
    t = st.tree(tw, by="cycle")
    return {g["group"]: sum(g[c] for c in t["columns"]) for g in t["groups"]}
