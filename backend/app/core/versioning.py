"""A shared convention for versioning any component whose output ends
up in a persisted audit record (Milestone 9: "model and policy
versioning"). Names the dated `"YYYY-MM-DD.N"` format already used ad
hoc before this module existed — `app/security/policy_engine.py::POLICY_VERSION`
and `app/predictive/jackpot_risk/model.py::MODEL_VERSION` both follow
it, now checked rather than just conventionally hoped-for (see their
own tests). Deliberately does NOT provide a cross-module registry
that imports every versioned component — `app/predictive/` depends on
the `predictive` extra (scikit-learn) and `app/security/` must not
gain a hard dependency on it just to report a version string nothing
there currently uses. Each producing module stamps its OWN version at
the point of use instead (e.g. `decision_service.py` already imports
`policy_engine`, so it can cite `POLICY_VERSION` directly); this
module only validates the shared format.
"""

import re
from datetime import date

_VERSION_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(\d+)$")


def validate_version_format(version: str) -> None:
    match = _VERSION_PATTERN.match(version)
    if not match:
        raise ValueError(
            f"version {version!r} doesn't match the required 'YYYY-MM-DD.N' format"
        )
    try:
        date.fromisoformat(match.group(1))
    except ValueError as exc:
        raise ValueError(
            f"version {version!r} doesn't match the required 'YYYY-MM-DD.N' format "
            f"(the date portion isn't a real calendar date: {exc})"
        ) from exc
