"""v2 runtime: chapters/seek, settings, work items, drill-down lists, report,
and the v2 agent reflexes (HANDOFF_V2 E2/E10/E11/E12, §9)."""

import time

from fastapi.testclient import TestClient

from app.agents.station_ops.detectors import detect_risks
from app.agents.station_ops.loop import StationOpsAgentLoop
from app.main import app
from app.simulation.station_ops.model import StationOpsTwin
from app.simulation.station_ops.plan import build_preset
from app.simulation.station_ops.snapshot import build_snapshot


def test_v2_runtime_endpoints_end_to_end():
    c = TestClient(app)
    r = c.post(
        "/runtime/sessions",
        json={"preset": "pitch_day", "seed": 3, "mode": "advise", "speed": 0.25},
    )
    assert r.status_code == 200 and r.json()["pitch"] is True
    sid = r.json()["id"]
    for m in (165, 390, 600, 750, 930):
        t = time.time()
        assert c.post(f"/runtime/sessions/{sid}/seek", json={"minute": m}).status_code == 200
        assert time.time() - t < 3.0  # each chapter lands in < 3 s
    v = c.get(f"/runtime/sessions/{sid}/state").json()["views"]
    for key in (
        "receive_v2",
        "induct_v2",
        "stow_v2",
        "dwell_v2",
        "ageing_v2",
        "plan_vs_actual",
        "associate_performance",
        "shift_plan_v2",
        "cycles",
        "settings",
        "work_items_v2",
        "metric_specs",
        "chapters",
    ):
        assert key in v, key
    assert v["cycles"]["pick_started"]
    # settings: editable thresholds only, validated
    assert (
        c.patch(f"/runtime/sessions/{sid}/settings", json={"stow_wip_lower_min": 12}).status_code
        == 200
    )
    assert (
        c.patch(f"/runtime/sessions/{sid}/settings", json={"stow_wip_lower_min": 40}).status_code
        == 422
    )
    # drill-down list length equals the count shown
    tree = v["dwell_v2"]["by_cycle"]
    g = next(x for x in tree["groups"] if x["CYCLE_1"])
    got = c.get(
        f"/runtime/sessions/{sid}/packages", params={"group": g["group"], "column": "CYCLE_1"}
    ).json()
    assert got["count"] == g["CYCLE_1"] == len(got["items"])
    # work items: complete one
    pending = [
        i
        for i in v["work_items_v2"]["items"]
        if i["state"] == "pending" and not i["id"].startswith("REC-")
    ]
    if pending:
        done = c.post(f"/runtime/sessions/{sid}/work-items/{pending[0]['id']}/complete").json()
        assert done["state"] == "done"
    # report
    rep = c.get(f"/runtime/sessions/{sid}/report").json()
    assert rep["simulated"] is True and rep["dea"]["headline"]
    # backward seek replays deterministically
    back = c.post(f"/runtime/sessions/{sid}/seek", json={"minute": 300}).json()
    assert back["seek"] == "replayed" and back["minute"] == 300


def test_pick_start_reflex_changes_cycle_and_enables_next():
    tw = StationOpsTwin(build_preset("ferry_disruption", 2))
    tw.run_until(605)
    loop = StationOpsAgentLoop("autopilot", futures=1)
    risks = {r.risk_type for r in detect_risks(tw, build_snapshot(tw, 0))}
    assert "late_volume_at_pick_start" in risks
    loop.step(tw, build_snapshot(tw, 0))
    kinds = {a["kind"] for a in tw.applied}
    assert {"change_cycle", "enable_cycle"} <= kinds


def test_full_finger_reflex_rebalances():
    tw = StationOpsTwin(build_preset("normal_day", 2))
    tw.config.sort.finger_bay_capacity = 60
    tw.run_until(270)
    loop = StationOpsAgentLoop("autopilot", futures=1)
    loop.step(tw, build_snapshot(tw, 0))
    assert any(a["kind"] == "rebalance_finger" for a in tw.applied)


def test_planning_agent_posts_opportunities_from_recommendations():
    tw = StationOpsTwin(build_preset("peak_volume", 5))
    loop = StationOpsAgentLoop("autopilot", futures=1)
    while tw.closeout.headcount is None and tw.now_minute < 1200:
        tw.run_until(tw.now_minute + 15)
    tw.closeout.roster = [p for p in tw.closeout.roster if p["flex"]] + [
        p for p in tw.closeout.roster if not p["flex"]
    ][:12]  # a thin roster tomorrow → shortfall
    loop.step(tw, build_snapshot(tw, 0))
    assert (
        any(a["kind"] == "post_opportunity" for a in tw.applied) or tw.closeout.opportunities.items
    )
