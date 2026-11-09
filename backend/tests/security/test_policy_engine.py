from app.rl.env import MIN_PRIORITY_WEIGHT
from app.security.policy_engine import CandidateIntervention, evaluate


def _candidate(name: str, weights: dict) -> CandidateIntervention:
    return CandidateIntervention(name=name, description="test candidate", priority_weights=weights)


def test_eligible_decision_type_with_valid_weights_has_no_violations():
    result = evaluate(
        "aisle_stow_priority",
        [_candidate("c1", {"A1": 0.5, "A2": 0.9})],
    )
    assert result.eligible is True
    assert result.violations == []


def test_unknown_decision_type_is_ineligible():
    result = evaluate(
        "summon_more_stowers",
        [_candidate("c1", {"A1": 0.5})],
    )
    assert result.eligible is False
    assert any("not on the eligible-pathway allow-list" in v for v in result.violations)


def test_weight_below_anti_starvation_floor_is_a_violation():
    result = evaluate(
        "aisle_stow_priority",
        [_candidate("c1", {"A1": MIN_PRIORITY_WEIGHT / 2})],
    )
    assert result.eligible is False
    assert any("anti-starvation floor" in v for v in result.violations)


def test_weight_at_exactly_the_floor_is_not_a_violation():
    result = evaluate(
        "aisle_stow_priority",
        [_candidate("c1", {"A1": MIN_PRIORITY_WEIGHT})],
    )
    assert result.eligible is True


def test_weight_outside_unit_interval_is_a_violation():
    result = evaluate(
        "aisle_stow_priority",
        [_candidate("c1", {"A1": 1.5})],
    )
    assert result.eligible is False
    assert any("outside [0, 1]" in v for v in result.violations)


def test_multiple_candidates_each_independently_checked():
    result = evaluate(
        "aisle_stow_priority",
        [_candidate("good", {"A1": 0.5}), _candidate("bad", {"A1": 0.0})],
    )
    assert result.eligible is False
    assert len(result.violations) == 1
    assert "bad" in result.violations[0]


def test_station_ops_candidates_are_bounded_by_lever_limits():
    from app.security.policy_engine import evaluate_station_ops

    ok = evaluate_station_ops(
        [{"name": "a", "interventions": [{"kind": "add_stowers", "amount": 4}]}]
    )
    assert ok.eligible
    bad = evaluate_station_ops(
        [
            {"name": "b", "interventions": [{"kind": "add_stowers", "amount": 40}]},
            {"name": "c", "interventions": [{"kind": "fire_everyone", "amount": 1}]},
            {"name": "d", "interventions": []},
        ]
    )
    assert not bad.eligible and len(bad.violations) == 3
