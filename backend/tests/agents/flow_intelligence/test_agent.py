"""Evaluation tests for the Flow Intelligence Agent — the Milestone 5
exit criteria: "given a synthetic Cycle-1 scenario with an induced
jackpot backlog, the agent produces a correctly-categorized finding
(not a recommendation) citing real evidence from Milestones 2-4's
data."

Uses a hand-built DuckDB fixture matching the real dbt project's table
shapes (tests/helpers/duckdb_fixtures.py), not a live dbt run — these
tests are about the agent's own logic, not re-verifying the analytics
pipeline (covered in Milestone 3/4's own suites). The literal end-to-end
scenario (real synthetic generator -> Postgres -> Parquet -> dbt ->
agent) was run and verified manually this session; see HANDOFF.md.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.agents.flow_intelligence.agent import (
    AGENT,
    build_fallback_output,
    gather_evidence,
    interpret,
)
from app.agents.flow_intelligence.schemas import (
    FlowIntelligenceInput,
    LLMFinding,
    LLMInterpretation,
)
from app.agents.schemas import EvidenceCategory
from app.core.llm.base import LLMProviderError
from app.core.llm.fake import FakeLLMProvider
from app.orchestration.models import AgentExecution, AgentExecutionStatus
from app.orchestration.runner import AgentExecutor
from tests.helpers.duckdb_fixtures import build_metrics_duckdb


def _jackpot_backlog_duckdb(tmp_path) -> str:
    """The induced-jackpot-backlog scenario the exit criteria names."""
    path = tmp_path / "metrics.duckdb"
    build_metrics_duckdb(
        path,
        cumulative_diverts=12,
        cumulative_clears=4,  # 8 still stuck — a real backlog, not a blip
        wip_count=8,
        dwell_rows=[
            ("P1", datetime(2026, 1, 1, 2, tzinfo=UTC), datetime(2026, 1, 1, 2, 5, tzinfo=UTC)),
            ("P2", datetime(2026, 1, 1, 2, tzinfo=UTC), datetime(2026, 1, 1, 2, 20, tzinfo=UTC)),
        ],
    )
    return str(path)


def test_gather_evidence_calls_exactly_the_declared_tools(tmp_path):
    duckdb_path = _jackpot_backlog_duckdb(tmp_path)
    evidence = gather_evidence(FlowIntelligenceInput(duckdb_path=duckdb_path))

    assert set(evidence) == {
        "jackpot_volume",
        "wips",
        "induct_throughput",
        "stow_throughput",
        "parcel_dwell_time",
    }
    assert evidence["jackpot_volume"]["currently_in_jackpot"] == 8


def test_deterministic_observation_cites_real_jackpot_evidence(tmp_path):
    """The exit criterion, satisfied without any LLM involved: the
    deterministic path alone produces a correctly-categorized
    OBSERVATION finding citing the real jackpot backlog.
    """
    duckdb_path = _jackpot_backlog_duckdb(tmp_path)
    evidence = gather_evidence(FlowIntelligenceInput(duckdb_path=duckdb_path))
    llm = FakeLLMProvider([LLMInterpretation(findings=[])])

    output = interpret(FlowIntelligenceInput(duckdb_path=duckdb_path), evidence, llm)

    jackpot_findings = [
        f
        for f in output.findings
        if f.category == EvidenceCategory.OBSERVATION and "jackpot" in f.summary.lower()
    ]
    assert len(jackpot_findings) == 1
    finding = jackpot_findings[0]
    assert "8" in finding.summary  # currently_in_jackpot
    assert finding.supporting_evidence == ["metric_jackpot_volume"]
    assert finding.category != EvidenceCategory.RECOMMENDATION


def test_llm_findings_are_merged_and_correctly_categorized(tmp_path):
    duckdb_path = _jackpot_backlog_duckdb(tmp_path)
    evidence = gather_evidence(FlowIntelligenceInput(duckdb_path=duckdb_path))

    scripted = LLMInterpretation(
        findings=[
            LLMFinding(
                category=EvidenceCategory.HYPOTHESIS,
                summary="The jackpot backlog may indicate reduced stower throughput.",
                supporting_evidence=["metric_jackpot_volume", "metric_stow_throughput"],
                alternative_explanations=["Could also be a temporary surge in induct volume."],
            )
        ]
    )
    llm = FakeLLMProvider([scripted])

    output = interpret(FlowIntelligenceInput(duckdb_path=duckdb_path), evidence, llm)

    hypothesis_findings = [f for f in output.findings if f.category == EvidenceCategory.HYPOTHESIS]
    assert len(hypothesis_findings) == 1
    assert hypothesis_findings[0].summary == scripted.findings[0].summary
    assert output.interpretation_error is None


def test_llm_finding_schema_rejects_observation_and_recommendation_categories():
    """Structural enforcement, not convention: the LLM literally cannot
    produce a category reserved for the deterministic path, or a
    recommendation (out of scope — no Layer 5 to approve one yet).
    """
    with pytest.raises(ValidationError):
        LLMFinding(category=EvidenceCategory.OBSERVATION, summary="should be rejected")

    with pytest.raises(ValidationError):
        LLMFinding(category=EvidenceCategory.CALCULATED, summary="should be rejected")

    with pytest.raises(ValidationError):
        LLMFinding(category=EvidenceCategory.RECOMMENDATION, summary="should be rejected")


def test_fallback_output_keeps_deterministic_findings_and_flags_the_error(tmp_path):
    duckdb_path = _jackpot_backlog_duckdb(tmp_path)
    evidence = gather_evidence(FlowIntelligenceInput(duckdb_path=duckdb_path))

    output = build_fallback_output(
        FlowIntelligenceInput(duckdb_path=duckdb_path), evidence, "provider unreachable"
    )

    assert output.interpretation_error == "provider unreachable"
    assert any(f.category == EvidenceCategory.OBSERVATION for f in output.findings)
    # Never fabricates an LLM-sourced finding in place of the real thing.
    llm_categories = (
        EvidenceCategory.INFERRED,
        EvidenceCategory.HYPOTHESIS,
        EvidenceCategory.PREDICTION,
    )
    assert not any(f.category in llm_categories for f in output.findings)


def test_end_to_end_through_the_real_executor_with_jackpot_backlog(tmp_path, db_session):
    """The full exit-criteria scenario: a real AgentExecutor run, a real
    AgentExecution audit row, the real AGENT definition — only the LLM
    is faked, per this session's project-owner decision (no live Ollama
    server configured; docs/OPEN_QUESTIONS.md).
    """
    duckdb_path = _jackpot_backlog_duckdb(tmp_path)
    scripted = LLMInterpretation(
        findings=[
            LLMFinding(
                category=EvidenceCategory.INFERRED,
                summary=(
                    "Jackpot clears are lagging diverts, consistent with a stower "
                    "capacity shortfall."
                ),
                supporting_evidence=["metric_jackpot_volume"],
            )
        ]
    )
    llm = FakeLLMProvider([scripted])
    executor = AgentExecutor(db_session, llm)

    output = executor.run(AGENT, FlowIntelligenceInput(duckdb_path=duckdb_path))

    assert any(f.category == EvidenceCategory.OBSERVATION for f in output.findings)
    assert any(f.category == EvidenceCategory.INFERRED for f in output.findings)
    assert not any(f.category == EvidenceCategory.RECOMMENDATION for f in output.findings)
    assert output.interpretation_error is None

    execution = (
        db_session.query(AgentExecution)
        .filter(AgentExecution.agent_name == "flow_intelligence")
        .one()
    )
    assert execution.status == AgentExecutionStatus.COMPLETED.value
    assert execution.checkpoint["jackpot_volume"]["currently_in_jackpot"] == 8
    assert execution.output == output.model_dump(mode="json")


def test_end_to_end_degrades_gracefully_when_llm_is_unavailable(tmp_path, db_session):
    duckdb_path = _jackpot_backlog_duckdb(tmp_path)
    llm = FakeLLMProvider([LLMProviderError("connection refused")] * (AGENT.max_retries + 1))
    executor = AgentExecutor(db_session, llm)

    output = executor.run(AGENT, FlowIntelligenceInput(duckdb_path=duckdb_path))

    assert output.interpretation_error is not None
    assert any(f.category == EvidenceCategory.OBSERVATION for f in output.findings)

    execution = (
        db_session.query(AgentExecution)
        .filter(AgentExecution.agent_name == "flow_intelligence")
        .one()
    )
    assert execution.status == AgentExecutionStatus.DEGRADED.value
