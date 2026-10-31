from app.orchestration.repository import create_execution, list_executions


def test_list_executions_filters_by_agent_name(db_session):
    create_execution(db_session, agent_name="flow_intelligence", input_payload={"a": 1})
    create_execution(db_session, agent_name="other_agent", input_payload={"b": 2})

    flow_only = list_executions(db_session, agent_name="flow_intelligence")

    assert all(e.agent_name == "flow_intelligence" for e in flow_only)
    assert not any(e.agent_name == "other_agent" for e in flow_only)


def test_list_executions_without_filter_returns_everything(db_session):
    before = len(list_executions(db_session))
    create_execution(db_session, agent_name="flow_intelligence", input_payload={})

    after = list_executions(db_session)

    assert len(after) == before + 1


def test_list_executions_filtered_returns_exactly_the_matching_rows(db_session):
    # Not asserting strict recency order here: Postgres's `now()`
    # (created_at's server_default) reflects transaction start time,
    # not per-statement time, so two rows inserted within this same
    # test's one uncommitted transaction can get an identical
    # created_at — a real Postgres characteristic, not a bug in
    # list_executions, and not meaningfully testable within one
    # transaction. Real usage spans separate requests/transactions,
    # where this isn't ambiguous.
    first = create_execution(db_session, agent_name="order_test", input_payload={"n": 1})
    second = create_execution(db_session, agent_name="order_test", input_payload={"n": 2})

    results = list_executions(db_session, agent_name="order_test")

    assert {r.id for r in results} == {first.id, second.id}
