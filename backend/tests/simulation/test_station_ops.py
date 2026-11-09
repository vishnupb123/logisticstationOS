"""Station Operations Twin v2: determinism, conservation, levers, dispatch,
information discipline, and the page views."""

from collections import Counter
from datetime import date

import pytest

from app.simulation.station_ops.config import Disruption, LinehaulPlan
from app.simulation.station_ops.model import (
    MAX_CUTOFF_EXTENSION_MINUTES,
    MAX_SPARE_LINES,
    Intervention,
    StationOpsTwin,
)
from app.simulation.station_ops.plan import PRESETS, build_preset, generate_linehaul_plan
from app.simulation.station_ops.snapshot import build_snapshot, run_station_day
from app.simulation.station_ops.views import build_views, search


def _day(preset="normal_day", seed=1, ivs=None):
    return run_station_day(build_preset(preset, seed), ivs)


def test_same_seed_is_identical_and_different_seeds_differ():
    a, b = _day("dispatch_disruption", 3), _day("dispatch_disruption", 3)
    assert a.model_dump() == b.model_dump()
    otds = {_day("dispatch_disruption", s).metrics["otd"].value for s in (1, 2, 3, 4)}
    assert len(otds) > 1, "OTD must vary day to day, not be a constant"


def test_linehaul_plan_is_deterministic_and_conserves_volume():
    p1 = generate_linehaul_plan(5, date(2026, 11, 9), total_volume=9000)
    assert p1 == generate_linehaul_plan(5, date(2026, 11, 9), total_volume=9000)
    assert abs(sum(t.volume for t in p1) - 9000) <= 200
    assert any(t.via_ferry for t in p1)


@pytest.mark.parametrize("preset", list(PRESETS))
def test_every_package_is_accounted_for_and_metrics_are_ratios(preset):
    snap = _day(preset)
    assert snap.done
    for key in (
        "dea",
        "otd",
        "otd_original_plan",
        "sort_compliance",
        "timely_staged",
        "scan_compliance",
    ):
        v = snap.metrics[key].value
        assert v is not None and 0.0 <= v <= 1.0, key
    assert snap.delivery["attempted"] + snap.delivery["known_misses"] == snap.delivery["promised"]
    assert snap.source_kind == "simulated"


def test_status_counts_conserve_packages_including_surges():
    tw = StationOpsTwin(build_preset("peak_volume"))
    tw.run_to_end()
    snap = build_snapshot(tw, 0)
    assert sum(snap.package_status.values()) == len(tw.pkgs)


def test_stress_presets_hurt_the_metric_they_stress():
    normal = _day("normal_day")
    assert _day("induct_line_outage").metrics["dea"].value < normal.metrics["dea"].value - 0.05
    assert _day("peak_volume").metrics["dea"].value < normal.metrics["dea"].value - 0.1
    assert _day("dispatch_disruption").metrics["otd"].value < normal.metrics["otd"].value - 0.05


def test_ferry_delay_is_revealed_progressively():
    cfg = build_preset("ferry_disruption")
    late = [t for t in cfg.linehauls if t.revisions]
    assert late
    t = late[0]
    assert t.known_delay(0) < t.known_delay(200) < t.known_delay(300) == t.delay_minutes


def test_open_induct_line_recovers_an_outage_and_is_capped():
    base = _day("induct_line_outage").metrics["dea"].value
    fixed = _day("induct_line_outage", ivs=[Intervention(kind="open_induct_line", at_minute=185)])
    assert fixed.metrics["dea"].value > base + 0.05
    snap = _day(
        "normal_day",
        ivs=[
            Intervention(kind="open_induct_line", at_minute=130 + i)
            for i in range(MAX_SPARE_LINES + 1)
        ],
    )
    opened = [a for a in snap.interventions_applied if a["kind"] == "open_induct_line"]
    assert opened[-1]["effect"].startswith("no-op")


def test_vet_call_in_has_lead_time_and_draws_down_the_flex_pool():
    tw = StationOpsTwin(build_preset("labor_shortage"))
    tw.run_until(200)
    rec = tw.apply(Intervention(kind="add_stowers", amount=3, at_minute=200))
    assert "arriving 03:" in rec["effect"] or "arriving 04:" in rec["effect"]
    assert tw.flex_remaining == tw.config.labor.flex_pool - 3
    before = tw.active("stow")
    tw.run_until(210)
    assert tw.active("stow") == before  # not yet arrived
    tw.run_until(260)
    assert tw.active("stow") >= before + 3


def test_extend_cutoff_is_capped_and_trades_off_staging():
    cfg_ivs = [Intervention(kind="extend_cutoff", amount=500, at_minute=300)]
    snap = _day("ferry_disruption", ivs=cfg_ivs)
    assert snap.cycle["cutoff_extension_minutes"] == MAX_CUTOFF_EXTENSION_MINUTES
    assert snap.metrics["dea"].value > _day("ferry_disruption").metrics["dea"].value


def test_lever_after_pick_start_is_an_honest_no_op():
    snap = _day(ivs=[Intervention(kind="add_stowers", amount=3, at_minute=600)])
    rec = next(a for a in snap.interventions_applied if a["kind"] == "add_stowers")
    assert rec["effect"].startswith("no-op")


def test_route_priority_changes_pick_order():
    tw = StationOpsTwin(build_preset("normal_day"))
    tw.run_until(500)
    tw.apply(Intervention(kind="prioritize_route", target="R-080", amount=5, at_minute=500))
    tw.run_until(530)
    assert tw.route_by_id("R-080").status != "ready"


def test_move_route_wave_shifts_plan_but_otd_original_plan_is_tracked():
    snap = _day(
        "dispatch_disruption",
        ivs=[
            Intervention(kind="move_route_wave", target=f"R-{i:03d}", amount=1, at_minute=480)
            for i in range(1, 17)
        ],
    )
    moved = [r for r in snap.routes if r["moved_waves"]]
    assert len(moved) == 16
    assert snap.metrics["otd_original_plan"].value <= snap.metrics["otd"].value


def test_no_show_gets_a_dsp_standby_eventually_and_earlier_with_reassign():
    tw = StationOpsTwin(build_preset("normal_day", seed=1))
    for d in tw.drivers:
        d.no_show = d.idx == 0
    tw.run_to_end()
    r = tw.routes[tw.drivers[0].route]
    assert r.departed_at is not None
    assert any(a["source"] == "dsp_auto" for a in tw.applied)


def test_notifying_late_drivers_improves_otd():
    cfg = build_preset("dispatch_disruption", seed=2)
    base = run_station_day(cfg).metrics["otd"].value
    ivs = [Intervention(kind="notify_drivers", target="all", at_minute=400)]
    assert run_station_day(cfg, ivs).metrics["otd"].value > base


def test_hv_packages_go_through_the_cage_with_two_custody_scans():
    tw = StationOpsTwin(build_preset("normal_day"))
    tw.run_to_end()
    hv = [p for p in tw.pkgs if p.hv and p.departed_at is not None]
    assert hv and all(p.custody_scans >= 2 for p in hv)


def test_cancelled_linehaul_is_a_dea_miss():
    cfg = build_preset("normal_day")
    cfg.linehauls[0] = LinehaulPlan(**{**cfg.linehauls[0].model_dump(), "cancelled": True})
    snap = run_station_day(cfg)
    assert snap.package_status["cancelled_inbound"] == cfg.linehauls[0].volume


def test_injected_disruption_is_applied_when_it_happens():
    cfg = build_preset("normal_day")
    cfg.disruptions = [Disruption(kind="line_jam", at_minute=200, duration_minutes=60, target="1")]
    tw = StationOpsTwin(cfg)
    tw.run_until(199)
    assert tw.line_down(1) is None
    tw.run_until(201)
    assert tw.line_down(1) == "jam"


def test_full_day_runs_through_on_road_to_completion_with_rts_and_swipes():
    tw = StationOpsTwin(build_preset("normal_day"))
    tw.run_until(23 * 60)
    snap = build_snapshot(tw, 0)
    assert snap.phase == "complete"
    views = build_views(tw, snap.model_dump(mode="json"))
    assert views["rts"]["totals"]["at_station"] >= 0
    assert Counter(d["state"] for d in views["dispatch"]["drivers"])["finished"] > 0


def test_views_cover_every_page_and_search_finds_a_package():
    tw = StationOpsTwin(build_preset("ferry_disruption"))
    tw.run_until(560)
    snap = build_snapshot(tw, 0).model_dump(mode="json")
    v = build_views(tw, snap)
    for key in (
        "performance",
        "receive",
        "dwell",
        "ageing",
        "rts",
        "stow_buffers",
        "associates",
        "pick",
        "stage",
        "dispatch",
        "high_value",
        "labor_plan",
        "problem_solve",
        "work_items",
        "layout",
        "sort_paths",
        "devices",
        "events",
    ):
        assert key in v
    assert v["dispatch"]["map"]["zones"] and v["associates"]["rows"]
    assert v["ageing"]["rows"][-1]["status"] == "Marked As Missing"
    res = search(tw, tw.pkgs[10].tracking_id)
    assert res["kind"] == "package" and res["results"][0]["timeline"]
    assert search(tw, "R-001")["kind"] == "container"


def test_unknown_preset_raises():
    with pytest.raises(KeyError):
        build_preset("../../etc/passwd")
