"""Role-based access control for the decision-governance pipeline
(Milestone 9, docs/ENGINEERING_ROADMAP.md: "role-based access control
and permission boundaries"). This is the piece ADR-0009's own
Consequences section named as still missing after Milestone 7: the
approval *gate* existed (`approve_decision`/`reject_decision`), but
who was allowed to use it was unchecked — `approved_by` was a trusted
plain string, nothing more.

Deliberately simple and code-defined, not a database-backed
permission system: there is no real user/auth system yet (no login,
no session) for a database-backed role to attach to. This checks the
role an identity *claims* to hold against a fixed, auditable table —
the same "deliberately simple and rule-based, not learned" precedent
`app/security/policy_engine.py` set for the policy engine. If a real
auth system arrives later, it supplies the verified `Role` this module
already expects; this module's own checking logic doesn't need to
change.
"""

from enum import StrEnum


class Role(StrEnum):
    OPERATOR = "operator"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"


class RBACError(PermissionError):
    pass


#: Which decision types each role may decide (approve or reject) on.
#: "*" means any decision type, including ones not yet invented.
#: Deliberately narrow by default: OPERATOR can propose/investigate
#: (nothing here gates `propose_decision`) but cannot decide — only
#: SUPERVISOR and ADMIN can.
_ROLE_PERMISSIONS: dict[Role, frozenset[str] | str] = {
    Role.OPERATOR: frozenset(),
    Role.SUPERVISOR: frozenset({"aisle_stow_priority"}),
    Role.ADMIN: "*",
}


def can_approve(role: Role, decision_type: str) -> bool:
    permitted = _ROLE_PERMISSIONS.get(role, frozenset())
    return permitted == "*" or decision_type in permitted


def check_can_approve(role: Role, decision_type: str) -> None:
    if not can_approve(role, decision_type):
        raise RBACError(
            f"role {role.value!r} is not permitted to decide on decision_type {decision_type!r}"
        )
