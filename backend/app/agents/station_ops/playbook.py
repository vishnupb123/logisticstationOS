"""The agent's experience memory ("learning"): every counterfactual
evaluation is persisted as one playbook entry — situation (risk type,
scenario, minute, projected impact), action (interventions), and the
simulated result (metric deltas, score). `learned_effectiveness` turns
that history into per-(risk, lever) statistics the agent uses to order
and pre-select candidates, and the UI shows as "what the agent has
learned".

Honest scope: this is empirical, case-based learning from *simulated*
episodes — an accumulating record of which lever helped in which
situation — not a trained model, and never evidence about a real station.
"""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.agents.station_ops.counterfactual import Evaluation
from app.agents.station_ops.detectors import Risk
from app.db.postgres import Base


class PlaybookEntry(Base):
    __tablename__ = "agent_playbook_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    risk_type: Mapped[str] = mapped_column(String(64), index=True)
    candidate_name: Mapped[str] = mapped_column(String(160))
    lever_key: Mapped[str] = mapped_column(String(160), index=True)
    #: The situation the lever was tried in (see `situation_key`) — learning
    #: is conditioned on it, so "extend pick start" scored *after* an
    #: extension was already applied never counts against extending early.
    situation: Mapped[str] = mapped_column(String(160), index=True, default="")
    interventions: Mapped[list] = mapped_column(JSONB)
    scenario: Mapped[str] = mapped_column(String(64))
    seed: Mapped[int] = mapped_column(Integer)
    detected_at_minute: Mapped[float] = mapped_column(Float)
    projected_impact: Mapped[int] = mapped_column(Integer)
    delta_dea_pp: Mapped[float] = mapped_column(Float)
    delta_otd_pp: Mapped[float] = mapped_column(Float)
    delta_timely_staged_pp: Mapped[float] = mapped_column(Float)
    labor_hours: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    source_kind: Mapped[str] = mapped_column(String(16), default="simulated")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def lever_key(evaluation: Evaluation) -> str:
    return "+".join(f"{iv.kind}:{iv.amount:g}" for iv in evaluation.interventions)


def situation_key(risk: Risk, applied_kinds: list[str]) -> str:
    """Coarse, interpretable situation signature: time-of-night bucket plus
    which lever kinds are already in effect."""
    m = risk.detected_at_minute
    phase = "early" if m < 180 else "mid" if m < 360 else "late"
    prior = ",".join(sorted(set(applied_kinds))) or "none"
    return f"{phase}|prior:{prior}"


def record(
    session: Session,
    risk: Risk,
    evaluations: list[Evaluation],
    *,
    scenario: str,
    seed: int,
    applied_kinds: list[str] | None = None,
) -> None:
    situation = situation_key(risk, applied_kinds or [])
    for ev in evaluations:
        session.add(
            PlaybookEntry(
                risk_type=risk.risk_type,
                candidate_name=ev.name,
                lever_key=lever_key(ev),
                situation=situation,
                interventions=[iv.model_dump(mode="json") for iv in ev.interventions],
                scenario=scenario,
                seed=seed,
                detected_at_minute=risk.detected_at_minute,
                projected_impact=risk.projected_impact,
                delta_dea_pp=ev.delta_dea_pp,
                delta_otd_pp=ev.delta_otd_pp,
                delta_timely_staged_pp=ev.delta_timely_staged_pp,
                labor_hours=ev.labor_hours,
                score=ev.score,
            )
        )
    session.flush()


def learned_effectiveness(
    session: Session, risk_type: str | None = None, situation: str | None = None
) -> list[dict]:
    q = session.query(PlaybookEntry)
    if risk_type:
        q = q.filter(PlaybookEntry.risk_type == risk_type)
    if situation is not None:
        q = q.filter(PlaybookEntry.situation == situation)
    groups: dict[tuple[str, str, str], list[PlaybookEntry]] = defaultdict(list)
    for e in q.all():
        groups[(e.risk_type, e.situation, e.lever_key)].append(e)
    stats = []
    for (rt, situation, key), rows in groups.items():
        n = len(rows)
        stats.append(
            {
                "risk_type": rt,
                "situation": situation,
                "lever_key": key,
                "candidate_name": rows[-1].candidate_name,
                "episodes": n,
                "scenarios": sorted({r.scenario for r in rows}),
                "mean_score": round(sum(r.score for r in rows) / n, 3),
                "mean_delta_dea_pp": round(sum(r.delta_dea_pp for r in rows) / n, 3),
                "mean_delta_otd_pp": round(sum(r.delta_otd_pp for r in rows) / n, 3),
                "mean_delta_timely_staged_pp": round(
                    sum(r.delta_timely_staged_pp for r in rows) / n, 3
                ),
                "win_rate": round(sum(1 for r in rows if r.score > 0) / n, 3),
            }
        )
    stats.sort(key=lambda s: (s["risk_type"], s["situation"], -s["mean_score"]))
    return stats


def prior_scores(session: Session, risk_type: str, situation: str) -> dict[str, float]:
    return {
        s["lever_key"]: s["mean_score"]
        for s in learned_effectiveness(session, risk_type, situation)
    }
