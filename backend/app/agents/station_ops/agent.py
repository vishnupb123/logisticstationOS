"""Station Operations Agent — the persisted, auditable investigation
(same three-function contract as the Flow Intelligence Agent,
app/orchestration/runner.py::AgentDefinition).

    Agent: station_ops
    Responsibility: run the full-day station twin in advise mode, detect
        risks to DEA / OTD / timely staging / sort & scan compliance,
        evaluate mitigations counterfactually, and propose the best plan.
    Input schema: StationOpsAgentInput (preset, seed, until_minute; the
        API may also pass a truckfile-derived linehaul list)
    Output schema: StationOpsAgentOutput
    Tool permissions: the station twin + the agent's detectors /
        counterfactual evaluator only — no database writes during
        evidence gathering (the playbook is written by the API layer).
    Retry / timeout: LLM step only, 2 retries, 60 s per attempt.
    Failure handling: LLM unavailable -> deterministic findings and
        recommendations are still complete; status DEGRADED with
        interpretation_error set. Never fabricates an LLM finding.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.agents.schemas import EvidenceCategory, Finding
from app.agents.station_ops.loop import StationOpsAgentLoop
from app.core.llm.base import LLMProvider
from app.orchestration.runner import AgentDefinition
from app.simulation.station_ops.config import LinehaulPlan
from app.simulation.station_ops.model import StationOpsTwin, clock
from app.simulation.station_ops.plan import build_preset
from app.simulation.station_ops.snapshot import METRIC_DEFINITIONS, build_snapshot

AGENT_NAME = "station_ops"
MAX_RETRIES = 2
TIMEOUT_SECONDS = 60.0


class StationOpsAgentInput(BaseModel):
    preset: str = "ferry_disruption"
    seed: int = 1
    #: Investigate the day up to this minute (default: whole day).
    until_minute: float = Field(1440, ge=60, le=1440)
    linehauls: list[LinehaulPlan] | None = None
    source: Literal["synthetic_plan", "truckfile"] = "synthetic_plan"


class LLMNarrativeFinding(BaseModel):
    # Structurally restricted (CLAUDE.md): the LLM may only add inferences,
    # hypotheses, or predictions — never observations/calculations/recommendations.
    category: Literal["inferred", "hypothesis", "prediction"]
    summary: str
    supporting_evidence: list[str] = []
    confidence: float | None = Field(None, ge=0, le=1)


class LLMNarrative(BaseModel):
    findings: list[LLMNarrativeFinding] = []


class StationOpsAgentOutput(BaseModel):
    findings: list[Finding]
    actions: list[dict]
    final_metrics: dict
    interpretation_error: str | None = None
    llm_model: str | None = None


def _config(inp: StationOpsAgentInput):
    cfg = build_preset(inp.preset, inp.seed)
    if inp.linehauls is not None:
        cfg.linehauls = inp.linehauls
        cfg.source = "truckfile"
    return cfg


def gather_evidence(inp: StationOpsAgentInput) -> dict:
    twin = StationOpsTwin(_config(inp))
    loop = StationOpsAgentLoop("advise")
    minute = 60.0
    twin.run_until(minute)
    while not twin.done and minute < inp.until_minute:
        loop.step(twin, build_snapshot(twin, 0))
        minute += 15
        twin.run_until(minute)
    snap = build_snapshot(twin, 0)
    return {
        "scenario": twin.config.name,
        "seed": twin.config.seed,
        "clock": snap.clock,
        "done": snap.done,
        "metrics": {k: v.model_dump(mode="json") for k, v in snap.metrics.items()},
        "package_status": snap.package_status,
        "inbound": snap.inbound,
        "outbound": snap.outbound,
        "late_trips": [t for t in snap.trips if t["delay_minutes"] > 0],
        "actions": [a.model_dump(mode="json") for a in loop.actions],
    }


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.2%}"


def deterministic_findings(evidence: dict) -> list[Finding]:
    m = evidence["metrics"]
    findings = [
        Finding(
            category=EvidenceCategory.CALCULATED,
            summary=(
                f"[{evidence['scenario']}] at {evidence['clock']}: "
                f"DEA {_pct(m['dea']['value'])} (ceiling {_pct(m['dea_ceiling']['value'])}), "
                f"OTD {_pct(m['otd']['value'])}, "
                f"timely staged {_pct(m['timely_staged']['value'])}, "
                f"sort compliance {_pct(m['sort_compliance']['value'])}, scan compliance "
                f"{_pct(m['scan_compliance']['value'])} — all `proposed` metric definitions, "
                "simulated (not live operational truth)."
            ),
            supporting_evidence=[f"metric:{k}" for k in METRIC_DEFINITIONS],
        ),
        Finding(
            category=EvidenceCategory.OBSERVATION,
            summary=(
                f"Package status: {evidence['package_status']['rolled_over']} rolled over, "
                f"{evidence['package_status']['left_behind']} left behind (uncaught missorts), "
                f"{evidence['inbound']['trips_late']} late linehaul(s)."
            ),
            supporting_evidence=["package_status", "inbound"],
        ),
    ]
    for a in evidence["actions"]:
        risk = a["risk"]
        findings.append(
            Finding(
                category=EvidenceCategory(risk["category"]),
                summary=f"{a['clock']} — {risk['summary']}",
                supporting_evidence=[f"risk:{risk['risk_type']}"],
            )
        )
        if a.get("chosen") and not a.get("evaluations"):
            findings.append(
                Finding(
                    category=EvidenceCategory.RECOMMENDATION,
                    summary=f"{a['clock']} — {a.get('agent_label', 'agent')} coordination: "
                    f"{a['chosen']} "
                    f"({a['rationale']})",
                    supporting_evidence=[f"risk:{risk['risk_type']}"],
                )
            )
        elif a.get("chosen"):
            best = a["evaluations"][0]
            findings.append(
                Finding(
                    category=EvidenceCategory.RECOMMENDATION,
                    summary=(
                        f"{a['clock']} — recommend '{a['chosen']}': simulated DEA "
                        f"{best['delta_dea_pp']:+.2f}pp, OTD {best['delta_otd_pp']:+.2f}pp, timely "
                        f"staged {best['delta_timely_staged_pp']:+.2f}pp "
                        f"for {best['labor_hours']:.1f} "
                        "labor h. Requires human approval before any real action (ADR-0009)."
                    ),
                    supporting_evidence=[
                        f"counterfactual:{e['name']}" for e in a["evaluations"][:3]
                    ],
                    confidence=None,
                )
            )
        elif a.get("advisory"):
            findings.append(
                Finding(
                    category=EvidenceCategory.RECOMMENDATION,
                    summary=f"{a['clock']} — advisory: {a['advisory']}",
                    supporting_evidence=[f"risk:{risk['risk_type']}"],
                )
            )
    return findings


def _prompt(evidence: dict) -> str:
    m = evidence["metrics"]
    risks = "; ".join(
        f"{a['clock']} {a['risk']['risk_type']}: {a['risk']['summary']}"
        for a in evidence["actions"][:6]
    )
    return (
        f"Scenario {evidence['scenario']}. Metrics: DEA={m['dea']['value']}, "
        f"OTD={m['otd']['value']}, timely_staged={m['timely_staged']['value']}, "
        f"sort_compliance={m['sort_compliance']['value']}. Rolled over: "
        f"{evidence['package_status']['rolled_over']}. Late trips: "
        f"{[(t['trip_id'], t['origin'], t['delay_minutes']) for t in evidence['late_trips']]}. "
        f"Risks detected: {risks}. Give up to 3 short findings: root-cause hypotheses or "
        "predictions about tomorrow's risk. Do not restate numbers as new facts."
    )


_SYSTEM = (
    "You are the Station Operations Agent for StationOS, a decision-support tool for a "
    "fictional, simulated delivery station. Reply only with JSON matching the schema. Each "
    "finding's category must be 'inferred', 'hypothesis' or 'prediction'. Never invent numbers."
)


def interpret(inp: StationOpsAgentInput, evidence: dict, llm: LLMProvider) -> StationOpsAgentOutput:
    findings = deterministic_findings(evidence)
    narrative = llm.complete_structured(
        system_prompt=_SYSTEM,
        user_prompt=_prompt(evidence),
        response_model=LLMNarrative,
        timeout_seconds=TIMEOUT_SECONDS,
    )
    for f in narrative.findings[:3]:
        findings.append(
            Finding(
                category=EvidenceCategory(f.category),
                summary=f.summary,
                supporting_evidence=f.supporting_evidence or ["llm_narrative"],
                confidence=f.confidence,
            )
        )
    return StationOpsAgentOutput(
        findings=findings,
        actions=evidence["actions"],
        final_metrics=evidence["metrics"],
        llm_model=getattr(llm, "model_name", None),
    )


def build_fallback_output(
    inp: StationOpsAgentInput, evidence: dict, error: str
) -> StationOpsAgentOutput:
    return StationOpsAgentOutput(
        findings=deterministic_findings(evidence),
        actions=evidence["actions"],
        final_metrics=evidence["metrics"],
        interpretation_error=error,
    )


AGENT = AgentDefinition[StationOpsAgentInput, StationOpsAgentOutput](
    name=AGENT_NAME,
    gather_evidence=gather_evidence,
    interpret=interpret,
    build_fallback_output=build_fallback_output,
    max_retries=MAX_RETRIES,
    timeout_seconds=TIMEOUT_SECONDS,
)

__all__ = ["AGENT", "StationOpsAgentInput", "StationOpsAgentOutput", "clock"]
