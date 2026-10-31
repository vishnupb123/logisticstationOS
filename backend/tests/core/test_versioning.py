import pytest

from app.core.versioning import validate_version_format


def test_accepts_the_dated_format():
    validate_version_format("2026-10-31.1")
    validate_version_format("2026-01-01.42")


@pytest.mark.parametrize(
    "bad_version",
    ["2026-10-31", "v1.0", "2026-13-01.1", "", "2026-10-31.1.2"],
)
def test_rejects_anything_else(bad_version):
    with pytest.raises(ValueError, match="format"):
        validate_version_format(bad_version)


def test_policy_engine_version_follows_the_convention():
    from app.security.policy_engine import POLICY_VERSION

    validate_version_format(POLICY_VERSION)
