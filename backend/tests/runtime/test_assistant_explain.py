"""The assistant's analysis + retrieval + grounded-LLM path, and next-day chaining."""

import pytest

from app.core.llm.fake import FakeLLMProvider
from app.runtime.chat import GroundedAnswer, StationAssistant, grounded, parse, topic_of
from app.runtime.knowledge import Index, build_corpus
from app.runtime.session import StationSession
from app.simulation.station_ops.plan import build_preset


@pytest.fixture(scope="module")
def done_session():
    s = StationSession(build_preset("ferry_disruption", 2), mode="observe", speed=60)
    s.stop()  # drive the twin directly, deterministically
    with s.lock:
        s.twin.run_until(23 * 60)
    return s


@pytest.mark.parametrize(
    ("msg", "topic"),
    [
        ("what caused the dea to be low?", "dea"),
        ("why did OTD drop", "otd"),
        ("what's the status of the trucks and ferries?", "trucks"),
        ("how many vets were accepted for tomorrow?", "labor"),
        ("who called out for tomorrow?", "labor"),
        ("what is the volume for tomorrow?", "tomorrow"),
        ("what did the agents do?", "decisions"),
        ("how did the shift go?", "shift"),
        ("anything about gtdr?", "trucks"),
    ],
)
def test_questions_route_to_topics(msg, topic):
    intent, ent = parse(msg)
    assert intent == "explain" and ent["topic"] == topic
    assert topic_of(msg.lower()) == topic


def test_followups_reuse_the_last_topic(done_session):
    a = StationAssistant(done_session)
    first = a.handle("why did DEA drop?")
    assert first.data["topic"] == "dea"
    again = a.handle("what did you do about it?")
    assert again.intent == "explain" and again.data["topic"] == "dea"


def test_dea_explanation_attributes_misses_and_lists_decisions(done_session):
    r = StationAssistant(done_session).handle("what caused the dea to be low?")
    titles = [s["title"] for s in r.sections]
    assert "Where the misses came from" in titles
    assert "Late linehauls behind the rollover" in titles  # ferry_disruption: late ferry volume
    assert any(t.startswith("Decisions") for t in titles)
    assert "Impact" in titles  # replay without decisions
    assert r.sources and r.llm_status == "unavailable"
    misses = next(s for s in r.sections if s["title"] == "Where the misses came from")
    assert any("arrived after pick start" in line for line in misses["lines"])


def test_trucks_labor_and_tomorrow_answers_use_closeout_state(done_session):
    a = StationAssistant(done_session)
    trucks = a.handle("status of the trucks and ferries")
    assert "Tomorrow's truckfile" in trucks.reply
    labor = a.handle("how many vets were accepted for tomorrow?")
    assert "Tomorrow — headcount" in labor.reply
    tomorrow = a.handle("what is the volume for tomorrow?")
    assert "predicted OFD volume" in tomorrow.reply


def test_free_questions_are_answered_from_retrieval(done_session):
    r = StationAssistant(done_session).handle("grounded van windscreen")
    assert r.intent in ("ask", "yard", "explain")
    with done_session.lock:
        idx = Index(build_corpus(done_session.twin, done_session.loop))
    hits = idx.search("GTDR trailer late", k=3)
    assert hits and any(h.kind == "gtdr" for h in hits)


def test_grounding_rejects_invented_numbers():
    facts = [
        "DEA is 94.1% against a 99.0% target: 705 of 12,000 packages missed.",
        "pick start 09:00",
    ]
    assert grounded("DEA was 94.1%, with 705 of 12,000 missed after pick start at 09:00.", facts)
    assert not grounded("DEA was 91.3% because 800 packages were missed.", facts)
    assert not grounded("Pick started at 10:15.", facts)


def test_llm_summary_is_kept_only_when_grounded(done_session):
    good = GroundedAnswer(
        answer="DEA missed target mainly because a late ferry's volume rolled over."
    )
    bad = GroundedAnswer(answer="DEA was 42.0% because 9999 packages were lost to a fire.")
    r1 = StationAssistant(done_session, FakeLLMProvider([good])).handle("why did dea drop?")
    assert r1.llm_status == "grounded" and r1.llm_summary
    r2 = StationAssistant(done_session, FakeLLMProvider([bad])).handle("why did dea drop?")
    assert r2.llm_status == "withheld" and r2.llm_summary is None


def test_next_day_is_built_from_the_final_truckfile(done_session):
    with done_session.lock:
        co = done_session.twin.closeout
        cfg = co.next_day_config()
    assert cfg.day == 2 and cfg.source == "next_day"
    assert cfg.ofd_date == co.tomorrow and cfg.truckfile_version == co.truckfile_version
    tf_ids = {t["trip_id"] for t in co.trips if t["known_volume"] > 0}
    assert {lh.trip_id for lh in cfg.linehauls} <= tf_ids
    assert cfg.outbound.routes == co.plan["needs"]["routes"]
