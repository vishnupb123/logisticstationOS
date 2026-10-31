"""The policy engine (docs/SECURITY_AND_GOVERNANCE.md's governance
pipeline, stage 1: "is this type of action even eligible for this
pathway?"). Deliberately simple and rule-based, not learned — a
policy engine that itself needed training would be the thing it's
supposed to be checking. Two independent checks, both hard
constraints per ADR-0009 ("never expressed as something... an agent's
confidence score could override"):

1. The decision type itself must be on an explicit allow-list — an
   unrecognized decision type is ineligible by default, not permitted
   until proven dangerous.
2. Every candidate's proposed action must independently respect the
   anti-starvation floor (app/rl/env.py::MIN_PRIORITY_WEIGHT) — this
   duplicates a constraint the environment already enforces
   structurally, deliberately: defense in depth, not trust that the
   environment was the only thing that could have produced this
   candidate (a human-authored candidate, e.g., bypasses the
   environment entirely).
"""

from pydantic import BaseModel

from app.rl.env import MIN_PRIORITY_WEIGHT

POLICY_VERSION = "2026-10-31.1"

#: Decision types this policy engine is willing to evaluate at all.
#: Anything else is rejected outright — adding a new decision type is a
#: deliberate code change here, not something a candidate can opt into.
ELIGIBLE_DECISION_TYPES = {"aisle_stow_priority"}


class CandidateIntervention(BaseModel):
    name: str
    description: str
    priority_weights: dict[str, float]


class PolicyEngineResult(BaseModel):
    eligible: bool
    violations: list[str]
    policy_version: str = POLICY_VERSION


def evaluate(
    decision_type: str, candidates: list[CandidateIntervention]
) -> PolicyEngineResult:
    violations: list[str] = []

    if decision_type not in ELIGIBLE_DECISION_TYPES:
        violations.append(
            f"decision_type {decision_type!r} is not on the eligible-pathway allow-list"
        )

    for candidate in candidates:
        for aisle, weight in candidate.priority_weights.items():
            if not (0.0 <= weight <= 1.0):
                violations.append(
                    f"candidate {candidate.name!r}: weight for {aisle} ({weight}) "
                    "is outside [0, 1]"
                )
            elif weight < MIN_PRIORITY_WEIGHT:
                violations.append(
                    f"candidate {candidate.name!r}: weight for {aisle} ({weight}) "
                    f"is below the anti-starvation floor ({MIN_PRIORITY_WEIGHT})"
                )

    return PolicyEngineResult(eligible=len(violations) == 0, violations=violations)
