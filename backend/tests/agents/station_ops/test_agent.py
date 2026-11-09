"""Station Operations multi-agent system: detectors (information discipline),
belief futures, orchestrator modes, arbitration, learning, goals, the
persisted investigation and its LLM restriction / degraded path."""

import pytest

from app.agents.station_ops.agent import (
    AGENT,
    LLMNarrative,
    LLMNarrativeFinding,
    StationOpsAgentInput,
    build_fallback_output,
    gather_evidence,
    interpret,
)
from app.agents.station_ops.counterfactual import belief_configs, evaluate, score
from app.agents.station_ops.detectors import detect_risks
from app.agents.station_ops.loop import StationOpsAgentLoop
from app.agents.station_ops.mitigations import candidates_for
from app.core.llm.base import LLMProviderError
from app.core.llm.fake import FakeLLMProvider
from app.orchestration.models import AgentExecution, AgentExecutionStatus
from app.orchestration.runner import AgentExecutor
from app.simulation.station_ops.model import StationOpsTwin
from app.simulation.station_ops.plan import build_preset
from app.simulation.station_ops.snapshot import build_snapshot, run_station_day


def _twin_at(preset: str, minute: float, seed: int = 1) -> StationOpsTwin:
    twin = StationOpsTwin(build_preset(preset, seed))
    twin.run_until(minute)
    return twin


def _types(twin):
    return {r.risk_type for r in detect_risks(twin, build_snapshot(twin, 0))}


def test_ferry_risk_uses_only_the_revealed_eta():
    # At 01:00 only 35% of the delay is known — not enough to miss pick start yet.
    assert "late_linehaul_rollover" not in _types(_twin_at("ferry_disruption", 60))
    later = _twin_at("ferry_disruption", 300)
    risks = [
        r
        for r in detect_risks(later, build_snapshot(later, 0))
        if r.risk_type == "late_linehaul_rollover"
    ]
    assert risks and risks[0].category.value == "prediction" and risks[0].agent == "inbound"


def test_normal_day_raises_no_capacity_risks():
    for minute in (60, 240, 420):
        assert not _types(_twin_at("normal_day", minute)) & {
            "late_linehaul_rollover",
            "induct_capacity_shortfall",
            "stow_capacity_shortfall",
        }


def test_belief_futures_hide_unrevealed_information():
    twin = _twin_at("ferry_disruption", 60)
    cfgs = belief_configs(twin, 2)
    assert len(cfgs) == 2 and all(c.disruptions == [] for c in cfgs)
    late = [i for i, t in enumerate(twin.config.linehauls) if t.revisions]
    true_delay = twin.config.linehauls[late[0]].delay_minutes
    assert all(c.linehauls[late[0]].delay_minutes < true_delay * 0.8 for c in cfgs)
    assert cfgs[0].driver_seed != cfgs[1].driver_seed


def test_counterfactual_finds_the_spare_line_for_an_outage():
    # At 03:20 the agent knows L1 is jammed but NOT that L2 will jam at 05:00,
    # so its (belief) estimate is smaller than hindsight would say — by design.
    twin = _twin_at("induct_line_outage", 200)
    _, evals = evaluate(
        None,
        [],
        candidates_for("induct_line_down", twin, source="t"),
        twin=twin,
        futures=1,
        try_combination=False,
    )
    assert evals[0].delta_dea_pp > 1 and "spare induct line" in evals[0].name


def test_score_is_monotone_in_dea_and_penalises_labor():
    assert score(1, 0, 0, 0) > score(0, 0, 0, 0) > score(0, 0, 0, 10)


def _run(preset: str, mode: str, seed: int = 1):
    twin = StationOpsTwin(build_preset(preset, seed))
    loop = StationOpsAgentLoop(mode, futures=1)
    m = 60
    while not twin.done and m < 1440:
        twin.run_until(m)
        loop.step(twin, build_snapshot(twin, 0))
        m += 15
    twin.run_to_end()
    return twin, loop, build_snapshot(twin, 0)


def test_autopilot_recovers_an_outage_and_observe_never_acts():
    base = run_station_day(build_preset("induct_line_outage")).metrics["dea"].value
    twin, loop, snap = _run("induct_line_outage", "autopilot")
    assert snap.metrics["dea"].value > base + 0.05
    assert any(a.agent == "sort_stow" and a.applied for a in loop.actions)
    twin, loop, snap = _run("induct_line_outage", "observe")
    assert not any(a["source"].startswith("agent") for a in twin.applied)
    assert snap.metrics["dea"].value == base


def test_dispatch_agent_protects_otd_with_reflexes():
    base = run_station_day(build_preset("dispatch_disruption", 2)).metrics["otd"].value
    _, loop, snap = _run("dispatch_disruption", "autopilot", seed=2)
    assert snap.metrics["otd"].value > base
    assert any(a.agent == "dispatch" and a.kind == "reflex" and a.applied for a in loop.actions)


def test_advise_mode_queues_recommendations_without_applying():
    twin = _twin_at("induct_line_outage", 200)
    loop = StationOpsAgentLoop("advise", futures=1)
    actions = loop.step(twin, build_snapshot(twin, 0))
    assert any(a.status == "pending" for a in actions)
    assert not any(a["source"].startswith("agent") for a in twin.applied)


def test_arbitration_never_overspends_the_flex_pool():
    _, loop, _ = _run("peak_volume", "autopilot")
    spent = sum(
        int(iv.amount)
        for a in loop.actions
        if a.applied
        for iv in a.chosen_interventions
        if iv.kind in ("add_stowers", "add_pickers")
    )
    assert spent <= build_preset("peak_volume").labor.flex_pool


def test_chat_goal_is_pursued_and_applied():
    twin = _twin_at("induct_line_outage", 200)
    loop = StationOpsAgentLoop("advise", futures=1)
    a = loop.handle_goal(twin, "induct_line_down", "fix it")
    assert a.kind == "goal" and a.applied and a.applied_effects


def test_concurrent_line_outages_are_one_risk():
    twin = _twin_at("induct_line_outage", 310)
    risks = [
        r for r in detect_risks(twin, build_snapshot(twin, 0)) if r.risk_type == "induct_line_down"
    ]
    assert len(risks) == 1 and risks[0].evidence["lines"] == [1, 2]


def test_learning_is_conditioned_on_situation(db_session):
    from app.agents.station_ops import playbook

    twin = _twin_at("induct_line_outage", 200)
    risk = next(
        r for r in detect_risks(twin, build_snapshot(twin, 0)) if r.risk_type == "induct_line_down"
    )
    late_risk = risk.model_copy(update={"detected_at_minute": 400})
    _, evals = evaluate(
        None,
        [],
        candidates_for(risk.risk_type, twin, source="t"),
        twin=twin,
        futures=1,
        try_combination=False,
    )
    bad = [e.model_copy(update={"score": -9.0}) for e in evals]
    for _ in range(6):
        playbook.record(
            db_session, late_risk, bad, scenario="t", seed=1, applied_kinds=["open_induct_line"]
        )
    early = playbook.situation_key(risk, [])
    assert playbook.prior_scores(db_session, risk.risk_type, early) == {}
    late = playbook.situation_key(late_risk, ["open_induct_line"])
    assert all(v == -9.0 for v in playbook.prior_scores(db_session, risk.risk_type, late).values())


@pytest.fixture(scope="module")
def evidence():
    return gather_evidence(StationOpsAgentInput(preset="induct_line_outage", until_minute=240))


def test_llm_findings_are_restricted_and_appended(evidence):
    llm = FakeLLMProvider(
        [
            LLMNarrative(
                findings=[
                    LLMNarrativeFinding(
                        category="hypothesis", summary="The jam on L1 is the root cause."
                    )
                ]
            )
        ]
    )
    out = interpret(StationOpsAgentInput(), evidence, llm)
    cats = [f.category.value for f in out.findings]
    assert "hypothesis" in cats and "calculated" in cats and "recommendation" in cats
    with pytest.raises(ValueError):
        LLMNarrativeFinding(category="observation", summary="x")


def test_fallback_keeps_every_deterministic_finding(evidence):
    out = build_fallback_output(StationOpsAgentInput(), evidence, "ollama down")
    assert out.interpretation_error == "ollama down"
    assert any(f.category.value == "recommendation" for f in out.findings)


def test_executor_marks_degraded_not_failed_without_llm(db_session):
    llm = FakeLLMProvider([LLMProviderError("down")] * 3)
    out = AgentExecutor(db_session, llm).run(
        AGENT, StationOpsAgentInput(preset="induct_line_outage", until_minute=180)
    )
    assert out.interpretation_error
    row = (
        db_session.query(AgentExecution)
        .filter_by(agent_name="station_ops")
        .order_by(AgentExecution.created_at.desc())
        .first()
    )
    assert row.status == AgentExecutionStatus.DEGRADED.value and row.output["findings"]


def test_online_capacity_learning_uses_observed_throughput_under_a_standing_queue():
    from app.agents.station_ops.detectors import observed_induct_factor

    assert observed_induct_factor(_twin_at("normal_day", 100)) == 1.0  # before induct starts
    twin = _twin_at("peak_volume", 300)  # standing induct queue on a peak day
    assert len(twin.induct_q) > 150
    f = observed_induct_factor(twin)
    assert 0.5 <= f <= 1.0
