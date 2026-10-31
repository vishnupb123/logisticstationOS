"""Flow Intelligence Agent.

Full contract (docs/AGENTIC_ARCHITECTURE.md §"Per-agent contract"):

    Agent: flow_intelligence
    Responsibility: analyses induct, sortation, stow, WIPS, and jackpot
        metrics for Cycle 1, from the Milestone 3 analytics pipeline —
        the narrowest-scoped agent in the roster, since Cycle 1 data
        already exists end to end (Milestones 2-4).
    Input schema: FlowIntelligenceInput (duckdb_path)
    Output schema: FlowIntelligenceOutput (findings: list[Finding],
        interpretation_error: str | None)
    Tool permissions: exactly query_jackpot_volume, query_wips,
        query_induct_throughput, query_stow_throughput,
        query_parcel_dwell_time (tools.py) — no others
    Persistent state: one AgentExecution row per run
        (app/orchestration/models.py) — input, checkpointed evidence,
        output, status, timestamps
    Retry / timeout policy: up to 2 retries (3 attempts total) on the
        LLM interpretation step only, 30s timeout per attempt — evidence
        gathering is not retried, since it's deterministic and cheap
    Audit provenance: the AgentExecution row itself
    Evaluation criteria: deterministic findings' numbers must exactly
        match the DuckDB source; every finding carries a valid
        EvidenceCategory; LLM findings are restricted to
        inferred/hypothesis/prediction (never observation/calculated/
        recommendation) — see tests/agents/flow_intelligence/
    Failure handling: on exhausted LLM retries, returns the deterministic
        findings with interpretation_error set — never fabricates an
        LLM-sourced finding

The LLM's job is strictly interpretation layered on top of numbers the
analytics layer already computed — it never performs a calculation
itself (docs/ENGINEERING_ROADMAP.md Milestone 5 non-goal).
"""

from app.agents.flow_intelligence import tools
from app.agents.flow_intelligence.schemas import (
    FlowIntelligenceInput,
    FlowIntelligenceOutput,
    LLMInterpretation,
)
from app.agents.schemas import EvidenceCategory, Finding
from app.core.llm.base import LLMProvider
from app.orchestration.runner import AgentDefinition

AGENT_NAME = "flow_intelligence"
MAX_RETRIES = 2
TIMEOUT_SECONDS = 30.0

_SYSTEM_PROMPT = (
    "You are the Flow Intelligence Agent for StationOS, a logistics operations "
    "intelligence platform modelling a fictional delivery station. You analyse induct, "
    "sortation, stow, work-in-process, and jackpot metrics for one Cycle-1 operating "
    "window and surface INFERRED conclusions, HYPOTHESES about causes, or PREDICTIONS "
    "about near-term risk — never raw observations, those are already computed "
    "deterministically and are not your job. Every finding you produce must name which "
    "metric(s) it is reasoning from in supporting_evidence. Do not invent numbers — only "
    "reason about the figures given to you. If the evidence doesn't support a confident "
    "conclusion, return an empty findings list rather than speculating."
)


def gather_evidence(input_data: FlowIntelligenceInput) -> dict:
    return {
        "jackpot_volume": tools.query_jackpot_volume(input_data.duckdb_path),
        "wips": tools.query_wips(input_data.duckdb_path),
        "induct_throughput": tools.query_induct_throughput(input_data.duckdb_path),
        "stow_throughput": tools.query_stow_throughput(input_data.duckdb_path),
        "parcel_dwell_time": tools.query_parcel_dwell_time(input_data.duckdb_path),
    }


def _deterministic_findings(evidence: dict) -> list[Finding]:
    findings = [
        Finding(
            category=EvidenceCategory.OBSERVATION,
            summary=(
                f"Jackpot volume: {evidence['jackpot_volume']['currently_in_jackpot']} "
                f"parcel(s) currently in jackpot "
                f"({evidence['jackpot_volume']['cumulative_diverts']} cumulative diverts, "
                f"{evidence['jackpot_volume']['cumulative_clears']} cumulative clears)."
            ),
            supporting_evidence=["metric_jackpot_volume"],
        ),
        Finding(
            category=EvidenceCategory.OBSERVATION,
            summary=(
                f"Work in process: {evidence['wips']['wip_count']} parcel(s) "
                "inducted but not yet stowed."
            ),
            supporting_evidence=["metric_wips"],
        ),
    ]

    dwell = evidence["parcel_dwell_time"]
    if dwell["parcel_count"] > 0:
        findings.append(
            Finding(
                category=EvidenceCategory.CALCULATED,
                summary=(
                    f"Parcel dwell time (induct to stow) over {dwell['parcel_count']} "
                    f"stowed parcel(s): min {dwell['min_dwell_seconds']:.0f}s, "
                    f"avg {dwell['avg_dwell_seconds']:.0f}s, max {dwell['max_dwell_seconds']:.0f}s."
                ),
                supporting_evidence=["metric_parcel_dwell_time"],
            )
        )

    return findings


def _build_user_prompt(evidence: dict) -> str:
    return (
        "Evidence gathered this run:\n"
        f"- Jackpot volume: {evidence['jackpot_volume']}\n"
        f"- WIPS: {evidence['wips']}\n"
        f"- Induct throughput by hour: {evidence['induct_throughput']}\n"
        f"- Stow throughput by hour/stower: {evidence['stow_throughput']}\n"
        f"- Parcel dwell time stats: {evidence['parcel_dwell_time']}\n\n"
        "What, if anything, can you infer or hypothesize from this?"
    )


def interpret(
    input_data: FlowIntelligenceInput, evidence: dict, llm: LLMProvider
) -> FlowIntelligenceOutput:
    findings = _deterministic_findings(evidence)

    interpretation = llm.complete_structured(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=_build_user_prompt(evidence),
        response_model=LLMInterpretation,
        timeout_seconds=TIMEOUT_SECONDS,
    )
    for llm_finding in interpretation.findings:
        findings.append(
            Finding(
                category=EvidenceCategory(llm_finding.category),
                summary=llm_finding.summary,
                supporting_evidence=llm_finding.supporting_evidence,
                confidence=llm_finding.confidence,
                alternative_explanations=llm_finding.alternative_explanations,
            )
        )

    return FlowIntelligenceOutput(findings=findings)


def build_fallback_output(
    input_data: FlowIntelligenceInput, evidence: dict, error: str
) -> FlowIntelligenceOutput:
    return FlowIntelligenceOutput(
        findings=_deterministic_findings(evidence),
        interpretation_error=error,
    )


AGENT = AgentDefinition[FlowIntelligenceInput, FlowIntelligenceOutput](
    name=AGENT_NAME,
    gather_evidence=gather_evidence,
    interpret=interpret,
    build_fallback_output=build_fallback_output,
    max_retries=MAX_RETRIES,
    timeout_seconds=TIMEOUT_SECONDS,
)
