"""The multi-agent orchestrator: five specialist agents (Inbound, Sort & Stow,
Outbound, Dispatch, Quality & HV) coordinated by one loop.

Each cycle:
1. **Sense** — every specialist's detectors read the twin (known info only).
2. **Reflex** — cheap, low-risk coordination happens immediately (notify late
   drivers, send a standby for a no-show, prioritise at-risk routes, remind
   drivers to swipe, re-sequence the yard, reinforce the HV cage).
3. **Plan** — for risks that need a scarce or trade-off lever, the owning
   specialist proposes candidate plans; each is evaluated by *robust*
   counterfactual simulation over belief futures (counterfactual.py).
4. **Arbitrate** — the orchestrator walks risks in severity order and commits
   the flex (VET) pool and lever kinds as it goes, so two agents can't both
   spend the same people or fight over the same lever in one cycle; a
   deferred request is logged, not silently dropped.
5. **Act / recommend** — `autopilot` applies to the twin only; `advise`
   (copilot) queues recommendations for a human to approve; `observe` only
   reports. Nothing here can touch anything outside the in-memory twin.
6. **Learn** — every evaluation goes to the playbook, conditioned on the
   situation; levers with a consistently negative record are skipped.

`handle_goal` lets the chat assistant hand the orchestrator a goal ("fix stow
WIP", "protect OTD") that is pursued even below normal alert thresholds.
"""

from collections.abc import Callable
from contextlib import nullcontext
from itertools import count
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.schemas import EvidenceCategory
from app.agents.station_ops import playbook
from app.agents.station_ops.counterfactual import (
    Evaluation,
    Outcome,
    applied_log,
    belief_configs,
    evaluate_prepared,
)
from app.agents.station_ops.detectors import AGENT_LABEL, OWNER, Risk, detect_risks
from app.agents.station_ops.mitigations import (
    ADVISORY,
    EFFICIENCY_RISKS,
    candidates_for,
    reflexes_for,
)
from app.simulation.station_ops.model import Intervention, StationOpsTwin, clock
from app.simulation.station_ops.snapshot import StationOpsSnapshot, build_snapshot

Mode = Literal["observe", "advise", "autopilot"]
COOLDOWN_MINUTES = 45
REFLEX_COOLDOWN = 10
ADVISORY_COOLDOWN = 240
MIN_GAIN_SCORE = 0.25
MIN_EPISODES_TO_SKIP = 5
_ids = count(1)


class AgentAction(BaseModel):
    id: int = 0
    minute: float
    clock: str
    mode: Mode
    agent: str
    agent_label: str
    risk: Risk
    kind: Literal["reflex", "plan", "advisory", "observe", "goal"] = "plan"
    baseline: Outcome | None = None
    evaluations: list[Evaluation] = []
    learned_skips: list[str] = []
    deferred: list[str] = []
    chosen: str | None = None
    chosen_interventions: list[Intervention] = []
    applied: bool = False
    applied_effects: list[str] = []
    advisory: str | None = None
    rationale: str
    status: Literal["applied", "pending", "dismissed", "held", "reported"] = "reported"


def list_interventions(twin: StationOpsTwin) -> list[Intervention]:
    return applied_log(twin)


class StationOpsAgentLoop:
    def __init__(
        self,
        mode: Mode,
        session_factory: Callable[[], Session] | None = None,
        futures: int = 2,
        lock=None,
    ):
        #: Guards every read/write of the live twin when another thread is
        #: stepping it (the runtime session); simulations run outside it.
        self.lock = lock or nullcontext()
        self.mode = mode
        self.session_factory = session_factory
        self.futures = futures
        self._last: dict[str, float] = {}
        self.actions: list[AgentAction] = []
        self.current_risks: list[Risk] = []

    # --- learning ---------------------------------------------------------------

    def _priors(self, risk: Risk, twin: StationOpsTwin) -> dict[str, dict]:
        if self.session_factory is None:
            return {}
        situation = playbook.situation_key(risk, [a["kind"] for a in twin.applied])
        with self.session_factory() as s:
            return {
                x["lever_key"]: x
                for x in playbook.learned_effectiveness(s, risk.risk_type, situation)
            }

    def _record(self, risk: Risk, evaluations: list[Evaluation], twin: StationOpsTwin) -> None:
        if self.session_factory is None or not evaluations:
            return
        with self.session_factory() as s:
            playbook.record(
                s,
                risk,
                evaluations,
                scenario=twin.config.name,
                seed=twin.config.seed,
                applied_kinds=[a["kind"] for a in twin.applied],
            )
            s.commit()

    # --- main cycle -------------------------------------------------------------

    def _base(self, risk: Risk, twin: StationOpsTwin) -> dict:
        return {
            "id": next(_ids),
            "minute": twin.now_minute,
            "clock": clock(twin.now_minute),
            "mode": self.mode,
            "agent": risk.agent,
            "agent_label": AGENT_LABEL[risk.agent],
            "risk": risk,
        }

    def step(self, twin: StationOpsTwin, snap: StationOpsSnapshot) -> list[AgentAction]:
        with self.lock:
            risks = detect_risks(twin, snap)
        self.current_risks = risks
        now = twin.now_minute
        new: list[AgentAction] = []
        flex_budget = twin.flex_remaining
        used_kinds: set[str] = set()
        for risk in sorted(risks, key=lambda r: (r.severity != "critical", -r.projected_impact)):
            reflex = reflexes_for(risk, twin, source=f"agent_{self.mode}")
            if reflex:
                if risk.risk_type in ("wave_checkin_upcoming", "driver_late") or (
                    now - self._last.get(f"reflex:{risk.risk_type}", -1e9) >= REFLEX_COOLDOWN
                ):
                    self._last[f"reflex:{risk.risk_type}"] = now
                    new.append(self._reflex(risk, twin, reflex))
                if risk.risk_type not in _PLANNED:
                    continue
            cooldown = (
                COOLDOWN_MINUTES
                if risk.risk_type in _PLANNED or risk.risk_type in ADVISORY
                else ADVISORY_COOLDOWN
            )
            if risk.risk_type not in _PLANNED and risk.risk_type not in ADVISORY:
                continue
            if now - self._last.get(risk.risk_type, -1e9) < cooldown:
                continue
            self._last[risk.risk_type] = now
            action = self._plan(risk, twin, flex_budget, used_kinds)
            if action.applied or action.status == "pending":
                ivs = action.chosen_interventions
                flex_budget -= sum(
                    int(i.amount) for i in ivs if i.kind in ("add_stowers", "add_pickers")
                )
                used_kinds |= {i.kind for i in ivs}
            new.append(action)
        self.actions.extend(new)
        return new

    def _reflex(self, risk: Risk, twin: StationOpsTwin, ivs: list[Intervention]) -> AgentAction:
        base = self._base(risk, twin)
        names = ", ".join(sorted({f"{i.kind.replace('_', ' ')}" for i in ivs}))
        if self.mode == "observe":
            return AgentAction(
                **base,
                kind="observe",
                rationale=f"Observe mode: would {names}.",
                chosen=names,
                chosen_interventions=ivs,
            )
        if self.mode == "advise":
            return AgentAction(
                **base,
                kind="reflex",
                chosen=names,
                chosen_interventions=ivs,
                status="pending",
                rationale=f"Low-risk coordination recommended: {names}.",
            )
        with self.lock:
            effects = [
                twin.apply(i.model_copy(update={"at_minute": twin.now_minute}))["effect"]
                for i in ivs
            ]
        return AgentAction(
            **base,
            kind="reflex",
            chosen=names,
            chosen_interventions=ivs,
            applied=True,
            applied_effects=effects,
            status="applied",
            rationale="Immediate low-risk coordination (no simulation needed).",
        )

    def _plan(
        self,
        risk: Risk,
        twin: StationOpsTwin,
        flex_budget: int,
        used_kinds: set[str],
        *,
        force: bool = False,
    ) -> AgentAction:
        base = self._base(risk, twin)
        advisory = ADVISORY.get(risk.risk_type)
        if self.mode == "observe" and not force:
            return AgentAction(
                **base,
                kind="observe",
                advisory=advisory,
                rationale="Observe mode: risk reported, no evaluation run.",
            )
        if risk.risk_type not in _PLANNED:
            return AgentAction(
                **base,
                kind="advisory",
                advisory=advisory,
                status="reported",
                rationale="No simulatable lever for this risk; advisory only.",
            )
        priors = self._priors(risk, twin)
        cands, skips, deferred = [], [], []
        with self.lock:
            proposals = candidates_for(risk.risk_type, twin, source=f"agent_{self.mode}")
        for cand in proposals:
            key = "+".join(f"{iv.kind}:{iv.amount:g}" for iv in cand.interventions)
            p = priors.get(key)
            if p and p["episodes"] >= MIN_EPISODES_TO_SKIP and p["mean_score"] < 0 and not force:
                skips.append(
                    f"{cand.name} (mean score {p['mean_score']} over {p['episodes']} episodes)"
                )
                continue
            if cand.flex_needed > flex_budget:
                deferred.append(
                    f"{cand.name} (needs {cand.flex_needed} flex, {flex_budget} uncommitted)"
                )
                continue
            if {i.kind for i in cand.interventions} & used_kinds - {"move_associates"}:
                deferred.append(f"{cand.name} (lever already committed this cycle)")
                continue
            cands.append((p["mean_score"] if p else 0.0, cand))
        cands.sort(key=lambda x: -x[0])
        if not cands:
            return AgentAction(
                **base,
                learned_skips=skips,
                deferred=deferred,
                advisory=advisory,
                status="held",
                rationale="No eligible plan (all skipped from experience or deferred "
                "for resources).",
            )
        with self.lock:  # snapshot what is known; simulate outside the lock
            configs = belief_configs(twin, self.futures)
            applied = applied_log(twin)
        baseline, evaluations = evaluate_prepared(configs, applied, [c for _, c in cands[:6]])
        self._record(risk, evaluations, twin)
        if risk.risk_type in EFFICIENCY_RISKS:
            ok = [e for e in evaluations if e.delta_dea_pp >= -0.05 and e.delta_otd_pp >= -0.5]
            best = max(ok, key=lambda e: e.delta_dea_pp, default=None)
        else:
            best = (
                evaluations[0] if evaluations and evaluations[0].score >= MIN_GAIN_SCORE else None
            )
        if force and best is None and evaluations and evaluations[0].score > 0:
            best = evaluations[0]
        action = AgentAction(
            **base,
            baseline=baseline,
            evaluations=evaluations[:6],
            learned_skips=skips,
            deferred=deferred,
            advisory=advisory,
            chosen=best.name if best else None,
            chosen_interventions=best.interventions if best else [],
            status="held" if best is None else "reported",
            rationale=(
                f"Best of {len(evaluations)} plan(s) over "
                f"{evaluations[0].futures} belief future(s): "
                f"'{best.name}' — DEA {best.delta_dea_pp:+.2f}pp, OTD {best.delta_otd_pp:+.2f}pp, "
                f"timely-staged {best.delta_timely_staged_pp:+.2f}pp, {best.labor_hours:.1f} extra "
                f"labor h; robust score {best.score} (±{best.score_stdev})."
                if best
                else f"No plan cleared the minimum robust gain ({MIN_GAIN_SCORE}); "
                "holding — acting "
                "would cost more than it is expected to recover."
            ),
        )
        if best is None:
            return action
        if self.mode == "autopilot" or force:
            with self.lock:
                for iv in best.interventions:
                    rec = twin.apply(
                        iv.model_copy(
                            update={"at_minute": twin.now_minute, "source": f"agent_{self.mode}"}
                        )
                    )
                    action.applied_effects.append(rec["effect"])
            action.applied, action.status = True, "applied"
        else:
            action.status = "pending"
        return action

    def handle_goal(self, twin: StationOpsTwin, risk_type: str, summary: str) -> AgentAction:
        """A goal from the chat assistant: pursue it now, even below the usual
        alert threshold, and apply the best plan to the twin."""
        with self.lock:
            snap = build_snapshot(twin, 0)
            detected = {r.risk_type: r for r in detect_risks(twin, snap)}
        risk = detected.get(risk_type) or Risk(
            risk_type=risk_type,
            severity="info",
            category=EvidenceCategory.OBSERVATION,
            summary=summary,
            metric="dea",
            projected_impact=0,
            detected_at_minute=twin.now_minute,
            evidence={},
        )
        reflex = reflexes_for(risk, twin, source="agent_chat")
        if reflex and risk_type not in _PLANNED:
            prev, self.mode = self.mode, "autopilot"
            try:
                action = self._reflex(risk, twin, reflex)
            finally:
                self.mode = prev
            action.kind = "goal"
        else:
            action = self._plan(risk, twin, twin.flex_remaining, set(), force=True)
            action.kind = "goal"
        self.actions.append(action)
        return action


_PLANNED = {
    k
    for k in OWNER
    if k
    in {
        "late_linehaul_rollover",
        "yard_congestion",
        "induct_capacity_shortfall",
        "stow_capacity_shortfall",
        "induct_line_down",
        "stow_wip_above_band",
        "stow_wip_below_band",
        "problem_solve_backlog",
        "routes_at_risk",
    }
}
