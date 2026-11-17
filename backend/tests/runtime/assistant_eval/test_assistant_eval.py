"""Station Assistant golden evaluation (HANDOFF_V2 §10.2).

20 questions × 3 seeded days = 60 cases. For each case:
- routing: the question reaches the expected topic (target ≥ 0.95);
- fact recall: the numbers the answer must contain — computed independently
  from the twin — appear in the reply (target ≥ 0.9);
- grounding: an LLM summary that invents a number is withheld, and one built
  only from the analysis' own facts is kept (violations must be 0).

Runs with FakeLLMProvider (test-only); the real-model run is a manual step
documented in docs/HANDOFF_V2.md.
"""

import re

import pytest

from app.core.llm.fake import FakeLLMProvider
from app.runtime.chat import GroundedAnswer, StationAssistant, parse
from app.runtime.session import StationSession
from app.simulation.station_ops import metrics as engine
from app.simulation.station_ops.plan import build_preset

DAYS = [("ferry_disruption", 2), ("pitch_day", 3), ("peak_volume", 5)]


def _n(x) -> list[str]:
    """Ways a number may be written in an answer."""
    if isinstance(x, float) and not x.is_integer():
        return [f"{x}", f"{x:.1f}", f"{x:.2f}"]
    x = int(x)
    return [f"{x:,}", f"{x}"]


def _pct(v) -> list[str]:
    return [f"{v * 100:.1f}%", f"{v:.0%}"]


def facts_for(topic: str, tw) -> list[list[str]]:  # noqa: C901
    """Each inner list = acceptable spellings of one required fact."""
    k = tw.counters
    co = tw.closeout
    m = engine.compute(tw)
    if topic in ("dea", "shift"):
        from app.simulation.station_ops.snapshot import build_snapshot

        return [_pct(build_snapshot(tw, 0).metrics["dea"].value)]
    if topic == "otd":
        from app.simulation.station_ops.snapshot import build_snapshot

        return [_pct(build_snapshot(tw, 0).metrics["otd"].value)]
    if topic == "cycles":
        return [_n(k["next_cycle"]), _n(k["held_wrong_cycle"])]
    if topic == "quality":
        return [_n(m["lost_hours"]["value"]), _n(m["induct_downtime_dpmo"]["value"] or 0)]
    if topic == "stow_wip":
        return [_n(m["stow_wip_compliance"]["inputs"]["intervals"])]
    if topic == "receive":
        return [_n(sum(1 for p in tw.pkgs if not p.planned and p.arrived_at is not None))]
    if topic == "containers":
        pend = sum(
            1
            for c in tw.containers
            if any(
                tw.pkgs[i].status in ("pending_receive", "pending_induct", "inducting")
                for i in c["pkgs"]
            )
        )
        return [_n(pend)]
    if topic == "ageing":
        from app.simulation.station_ops.views_v2 import ageing_v2

        a = ageing_v2(tw)
        return [_n(len(a["missing_packages"])), _n(len(a["lost_packages"]))]
    if topic == "labor_plan":
        return [_n(co.labor_plan()["totals"]["show_hours"])]
    if topic == "rotation":
        return [_n(co.rotation_stats["slots"]), _n(co.rotation_stats["filled"])]
    if topic == "work_items":
        return [_n(tw.work_items.summary()["expired_today"])]
    if topic == "trucks":
        return [[f"v{co.truckfile_version}"]]
    if topic == "labor":
        return [_n(sum(len(o["accepted"]) for o in co.opportunities.items if o["type"] == "VET"))]
    if topic == "tomorrow":
        return [_n(co.known_ofd()["ofd_volume"])]
    if topic == "fingers":
        return [_n(tw.finger_stats["FINGER-A"]["full_bay"])]
    return []


QUESTIONS = [
    ("Why did DEA drop?", "dea"),
    ("why did OTD drop", "otd"),
    ("What happened at pick start?", "cycles"),
    ("Which line hurt us?", "quality"),
    ("Why was WIP out of band at 05:00?", "stow_wip"),
    ("How much unplanned volume came in?", "receive"),
    ("Which gaylords are still pending?", "containers"),
    ("What's ageing over 2 days?", "ageing"),
    ("Are we covered tomorrow 10:00-13:00?", "labor_plan"),
    ("Who can't do stow tomorrow and why?", "rotation"),
    ("What expired today?", "work_items"),
    ("Were we on plan at 07:00?", "plan_actual"),
    ("What's the status of the trucks and ferries?", "trucks"),
    ("How many VETs were accepted for tomorrow?", "labor"),
    ("What is the volume for tomorrow?", "tomorrow"),
    ("How did the shift go?", "shift"),
    ("Is finger A running into full bays?", "fingers"),
    ("What did the agents do?", "decisions"),
    ("Explain the no-read rate by line", "quality"),
    ("Show me the downtime DPMO", "quality"),
]


@pytest.fixture(scope="module")
def sessions():
    out = {}
    for preset, seed in DAYS:
        s = StationSession(build_preset(preset, seed), mode="observe", speed=60)
        s.stop()
        with s.lock:
            s.twin.run_until(23 * 60)
        out[(preset, seed)] = s
    return out


def test_routing_accuracy():
    ok = sum(
        1 for q, topic in QUESTIONS if parse(q) == ("explain", {"topic": topic, "text": q.lower()})
    )
    assert ok / len(QUESTIONS) >= 0.95, [
        (q, parse(q)) for q, t in QUESTIONS if parse(q)[1].get("topic") != t
    ]


def test_fact_recall_and_grounding(sessions):
    total = found = 0
    misses: list[str] = []
    violations = 0
    cases = 0
    for (_preset, _seed), s in sessions.items():
        for q, topic in QUESTIONS:
            cases += 1
            # grounding: an invented number must never get through
            bad = GroundedAnswer(answer=f"{q} — it was 987654 packages and 77.7%.")
            r = StationAssistant(s, FakeLLMProvider([bad])).handle(q)
            if r.llm_summary and "987654" in r.llm_summary:
                violations += 1
            reply = (
                r.reply
                + "\n"
                + "\n".join(line for sec in (r.sections or []) for line in sec.get("lines", []))
            )
            with s.lock:
                need = facts_for(topic, s.twin)
            for spellings in need:
                total += 1
                if any(re.search(re.escape(x) + r"(?![\d])", reply) for x in spellings):
                    found += 1
                else:
                    misses.append(f"{_preset}/{q}: expected one of {spellings}")
            # a summary made only of the analysis' own facts is kept
            if r.data and r.sections:
                headline = r.reply.strip().split("\n")[0]
                if headline:
                    good = GroundedAnswer(answer=headline)
                    r2 = StationAssistant(s, FakeLLMProvider([good])).handle(q)
                    assert r2.llm_status in ("grounded", "unavailable"), (q, r2.llm_status)
    print(
        f"assistant eval: {cases} cases, fact recall {found}/{total}, grounding violations {violations}"
    )
    assert cases >= 60
    assert violations == 0
    assert total and found / total >= 0.9, misses
