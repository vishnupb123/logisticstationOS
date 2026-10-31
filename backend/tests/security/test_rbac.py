import pytest

from app.security.rbac import RBACError, Role, can_approve, check_can_approve


def test_operator_can_approve_nothing():
    assert can_approve(Role.OPERATOR, "aisle_stow_priority") is False
    assert can_approve(Role.OPERATOR, "anything_at_all") is False


def test_supervisor_can_approve_the_known_decision_type():
    assert can_approve(Role.SUPERVISOR, "aisle_stow_priority") is True


def test_supervisor_cannot_approve_an_unknown_decision_type():
    assert can_approve(Role.SUPERVISOR, "summon_more_stowers") is False


def test_admin_can_approve_anything_including_future_decision_types():
    assert can_approve(Role.ADMIN, "aisle_stow_priority") is True
    assert can_approve(Role.ADMIN, "a_decision_type_invented_next_milestone") is True


def test_check_can_approve_raises_rbac_error_on_denial():
    with pytest.raises(RBACError, match="operator"):
        check_can_approve(Role.OPERATOR, "aisle_stow_priority")


def test_check_can_approve_is_silent_on_success():
    check_can_approve(Role.ADMIN, "aisle_stow_priority")  # no raise
