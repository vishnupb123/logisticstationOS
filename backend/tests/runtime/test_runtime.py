"""Live runtime sessions + Station Assistant chat (HTTP and in-process)."""

import time

import pytest

from app.runtime.chat import StationAssistant, parse
from app.runtime.session import SessionManager
from app.simulation.station_ops.plan import build_preset


@pytest.mark.parametrize(
    ("msg", "intent"),
    [
        ("status", "summary"),
        ("what's at risk?", "risks"),
        ("how is stow wip", "metric"),
        ("fix stow WIP", "fix_wip"),
        ("protect OTD", "protect_otd"),
        ("protect DEA from rollover", "protect_dea"),
        ("prioritise R-12", "action"),
        ("move R-031 to the next wave", "action"),
        ("notify late drivers", "action"),
        ("VET 3 stowers", "action"),
        ("simulate a jam on line 2 for 20 min", "action"),
        ("what if we vet 4 stowers", "what_if"),
        ("where is R-045?", "route_status"),
        ("late trucks", "linehauls"),
        ("pause", "control"),
        ("approve all", "approve"),
    ],
)
def test_intent_parser(msg, intent):
    assert parse(msg)[0] == intent


@pytest.fixture
def session():
    mgr = SessionManager()
    s = mgr.create(config=build_preset("induct_line_outage", 1), speed=60)
    yield s
    mgr.stop_all()


def _wait_minute(s, minute, timeout=30):
    end = time.time() + timeout
    while s.twin.now_minute < minute and time.time() < end:
        time.sleep(0.1)


def test_session_advances_and_exposes_every_view(session):
    _wait_minute(session, 200)
    state = session.state()
    assert state["snapshot"]["minute"] >= 200
    assert {"dispatch", "associates", "high_value", "labor_plan"} <= set(state["views"])
    assert state["agents"]["mode"] == "autopilot"


def test_chat_answers_and_acts_on_the_live_station(session):
    _wait_minute(session, 200)
    bot = StationAssistant(session)
    assert "DEA" in bot.handle("status").reply
    r = bot.handle("move 1 problem solve to stow")
    assert r.intent == "action" and "problem_solve → stow" in r.actions[0]["effect"]
    r = bot.handle("simulate a jam on line 2 for 20 min")
    assert "L2 jammed" in r.reply
    r = bot.handle("what if we vet 2 stowers")
    assert r.intent == "what_if" and "not applied" in r.reply
    r = bot.handle("pause")
    assert session.paused
    assert len(session.chat_history) == 10


def test_advise_mode_recommendations_can_be_approved(session):
    session.control(mode="advise")
    _wait_minute(session, 260)
    end = time.time() + 30
    while not [a for a in session.loop.actions if a.status == "pending"] and time.time() < end:
        time.sleep(0.2)
    pending = [a for a in session.loop.actions if a.status == "pending"]
    assert pending
    a = session.approve(pending[0].id)
    assert a.status == "applied"
    with pytest.raises(ValueError):
        session.approve(pending[0].id)


def test_runtime_http_api(client):
    created = client.post(
        "/runtime/sessions", json={"preset": "dispatch_disruption", "seed": 4, "speed": 60}
    ).json()
    sid = created["id"]
    try:
        time.sleep(1.5)
        st = client.get(f"/runtime/sessions/{sid}/state").json()
        assert st["session"]["id"] == sid and st["snapshot"]["scenario"] == "dispatch_disruption"
        r = client.post(
            f"/runtime/sessions/{sid}/actions", json={"kind": "notify_drivers", "target": "all"}
        )
        assert r.status_code == 200 and "notified" in r.json()["effect"]
        bad = client.post(
            f"/runtime/sessions/{sid}/actions", json={"kind": "add_stowers", "amount": 99}
        )
        assert bad.status_code == 422
        chat = client.post(f"/runtime/sessions/{sid}/chat", json={"message": "late drivers"}).json()
        assert chat["intent"] == "drivers"
        assert (
            client.get(f"/runtime/sessions/{sid}/search", params={"q": "R-001"}).json()["kind"]
            == "container"
        )
        assert client.post(f"/runtime/sessions/{sid}/control", json={"paused": True}).json()[
            "paused"
        ]
        assert (
            client.post(f"/runtime/sessions/{sid}/recommendations/999/approve").status_code == 409
        )
        assert client.get("/runtime/sessions/nope/state").status_code == 404
        assert client.post("/runtime/sessions", json={"preset": "../x"}).status_code == 404
    finally:
        from app.runtime.session import manager

        manager.stop_all()
