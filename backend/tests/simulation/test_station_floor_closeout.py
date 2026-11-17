"""Floor exceptions (wrong staging scan, forgotten bag + sweep, VSA/grounded
vans), the after-dispatch close-out (GTDR, truckfile, scrubs, VET/VTO,
tomorrow's plan), the planning/floor agents' reflexes, and the road map."""

from app.agents.station_ops.detectors import detect_risks
from app.agents.station_ops.loop import StationOpsAgentLoop
from app.simulation.station_ops import geo
from app.simulation.station_ops.model import Intervention, StationOpsTwin
from app.simulation.station_ops.plan import build_preset
from app.simulation.station_ops.snapshot import build_snapshot
from app.simulation.station_ops.views import build_views, city_map, driver_path


def _twin(seed=2, preset="normal_day", **overrides):
    cfg = build_preset(preset, seed)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return StationOpsTwin(cfg)


def test_wrong_staging_scan_notifies_and_is_restaged():
    tw = _twin()
    tw.config.outbound.misstage_notice_minutes = (60, 60)
    for r in tw.routes:
        r.misstage, r.misstage_notice_s = r.idx == 0, 3600
    while tw.routes[0].misstaged_since is None and tw.now_minute < 700:
        tw.run_until(tw.now_minute + 1)
    r = tw.routes[0]
    assert r.misstaged_at and r.misstaged_at != r.staging_location
    kinds = [n["kind"] for n in tw.notifications]
    assert "wrong_staging_scan" in kinds and "staging_change" in kinds  # supervisor + DSPs
    assert r.staged_at is None  # can't be staged while a cart is in the wrong place
    rec = tw.apply(Intervention(kind="restage_cart", target=r.route_id))
    assert "sent to move the cart" in rec["effect"]
    tw.run_until(tw.now_minute + 4)
    assert r.misstage_fixed_at is not None and r.misstaged_at is None
    assert r.misstage_fixed_at - r.misstaged_since < 10 * 60


def test_forgotten_bag_flagged_and_sweep_restages_it_before_departure():
    tw = _twin()
    for r in tw.routes:
        r.forget_bag = r.idx == 3
        r.misstage = False
    tw.run_to_end()
    r = tw.routes[3]
    assert r.forgotten > 0
    assert any(n["kind"] == "bag_not_loaded" for n in tw.notifications)
    recovered = [p for i in r.packages if (p := tw.pkgs[i]).recovered]
    assert recovered, "sweep or scrub should find the bag"
    assert tw.counters["sweep_staged"] + tw.counters["cluster_transfer"] > 0
    assert tw.sweep_log


def test_grounded_van_gets_replacement_and_departs():
    tw = _twin()
    target = tw.routes[0].driver
    for d in tw.drivers:
        d.vsa_u = 0.0 if d.idx == target else 0.99
        d.vsa_defect = "brake warning light" if d.idx == target else None
    tw.run_to_end()
    d = tw.drivers[target]
    assert d.vsa_result == "replaced"
    assert d.van_request is not None  # DSP default request after 20 min
    assert tw.routes[0].departed_at is not None
    assert any(n["kind"] == "van_grounded" for n in tw.notifications)


def test_agent_requests_replacement_van_faster_than_dsp_default():
    def run(mode):
        tw = _twin()
        target = tw.routes[10].driver
        for d in tw.drivers:
            d.vsa_u = 0.0 if d.idx == target else 0.99
        loop = StationOpsAgentLoop(mode, futures=1)
        while not tw.done and tw.now_minute < 900:
            tw.run_until(tw.now_minute + 1)
            if tw.urgent:
                tw.urgent = False
                loop.step(tw, build_snapshot(tw, 0))
        return tw.routes[10].departed_at

    assert run("autopilot") < run("observe")


def test_closeout_runs_to_completion_and_plans_tomorrow():
    tw = _twin(seed=5, preset="dispatch_disruption")
    tw.run_until(23 * 60)
    co = tw.closeout
    assert tw.day_complete and co.complete
    assert co.final_published_at is not None and co.truckfile_version >= 1
    assert co.plan is not None and co.plan["assignments"]
    assert 0 <= co.plan["rotation_compliance"] <= 1
    kinds = {t["kind"] for t in co.tasks}
    assert {"ferry_check", "publish_truckfile", "in_station_scrub", "headcount"} <= kinds
    assert all(t["status"] == "done" for t in co.tasks)
    assert {"in_station", "on_road"} <= set(co.scrubs)
    # v2: opportunities are posted only where the plan is unbalanced; associates
    # submit and the station accepts — nothing is left open after close-out
    assert co.offers or not co.opportunities.recommendations()
    assert all(o["status"] in ("accepted", "declined") for o in co.offers)
    assert co.readiness is not None and "staffing_gap" in co.readiness
    snap = build_snapshot(tw, 0).model_dump(mode="json")
    v = build_views(tw, snap)
    assert v["closeout"]["complete"] and v["closeout"]["plan"]["version"] >= 1


def test_ferry_revision_needs_a_check_and_triggers_replan_risk():
    tw = _twin(seed=5, preset="dispatch_disruption")
    while tw.closeout.final_published_at is None:
        tw.run_until(tw.now_minute + 5)
    co = tw.closeout
    tw.run_until(tw.now_minute + 40)  # headcount done
    rev = {
        "at": tw.now_minute - 1,
        "trip": next(i for i, t in enumerate(co.trips) if t["via_ferry"]),
        "field": "known_cancelled",
        "value": True,
        "check": True,
        "why": "test",
        "revealed": False,
    }
    co.revisions.append(rev)
    assert not rev["revealed"]  # ferry revisions wait for someone to check
    tw.apply(Intervention(kind="check_ferry"))
    tw.run_until(tw.now_minute + 6)
    assert rev["revealed"] and co.truckfile_version >= 2
    risks = {r.risk_type for r in detect_risks(tw, build_snapshot(tw, 0))}
    if co.headcount and co.headcount["truckfile_version"] != co.truckfile_version:
        assert "truckfile_changed_since_plan" in risks
    assert tw.apply(Intervention(kind="replan_next_day"))["effect"].startswith(
        ("manager re-plan", "no-op: re-plan already")
    )


def test_vet_submissions_fall_with_later_posting():
    # v2 (E7): associates submit to opportunities; earlier posting → more submissions
    tw = _twin()
    opp = tw.closeout.opportunities
    assert opp.submit_p("VET", 11 * 60, 150) > opp.submit_p("VET", 22 * 60, 150)


def test_road_map_paths_follow_roads():
    tw = _twin()
    city = geo.city_for(tw.config.station_code)
    assert len(city.roads) > 200 and city.bridges
    tw.run_until(12 * 60)
    d = next(x for x in tw.drivers if x.state == "on_road")
    p = driver_path(tw, d.driver_id)
    assert len(p["out"]) > 3 and len(p["tour"]) > 5
    assert city_map(tw)["zones"]
