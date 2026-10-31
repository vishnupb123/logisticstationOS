"""Risk evaluation (docs/SECURITY_AND_GOVERNANCE.md governance
pipeline, stage 3: "what's the blast radius / reversibility of acting
on this?"). ADR-0009's own Consequences section is explicit that this
"needs its own design work, tracked as an open question" — this is
deliberately that stub, not a finished risk model. It exists so the
decision-governance pipeline has a real stage to fill rather than a
placeholder with no code behind it, and so every DecisionRecord has
*something* here to review, honestly labeled as a minimal first cut
(see docs/OPEN_QUESTIONS.md).

The one honest thing it can say today: every decision type this
system can currently propose only affects the digital twin
(app/simulation/), never a live operational system (none exists) — so
blast radius is "simulation-only" and every outcome is reversible by
construction. A real risk model (differentiating decision types by
actual operational blast radius) is Milestone 9 work.
"""

from pydantic import BaseModel


class RiskEvaluation(BaseModel):
    blast_radius: str
    reversible: bool
    rationale: str


def evaluate_risk(decision_type: str) -> RiskEvaluation:
    return RiskEvaluation(
        blast_radius="simulation_only",
        reversible=True,
        rationale=(
            f"decision_type={decision_type!r} only affects a digital-twin simulation run; "
            "there is no live operational system for it to act on, so any outcome is "
            "reversible by construction. Not a general risk model — see docs/OPEN_QUESTIONS.md."
        ),
    )
