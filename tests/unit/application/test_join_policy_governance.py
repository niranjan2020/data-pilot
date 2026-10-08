import pytest

from datapilot.application.join_policy_governance import validate_governed_join_policy


REL = dict(from_schema="demo", from_table="events", from_column="asset_id",
           to_schema="demo", to_table="assets", to_column="id",
           cardinality="many_to_one", join_policy="preserve_source")


@pytest.mark.parametrize("sql,allowed", [
    ('SELECT e.id FROM demo.events e LEFT JOIN demo.assets a ON e.asset_id = a.id', True),
    ('SELECT e.id FROM demo.events e INNER JOIN demo.assets a ON e.asset_id = a.id', False),
    ('SELECT e.id FROM demo.events e JOIN demo.assets a ON e.asset_id = a.id', False),
    ('SELECT e.id FROM demo.events e RIGHT JOIN demo.assets a ON e.asset_id = a.id', False),
    ('SELECT e.id FROM demo.assets a LEFT JOIN demo.events e ON e.asset_id = a.id', False),
    ('SELECT e.id FROM demo.events e LEFT JOIN demo.assets a ON e.id = a.id', False),
    ('SELECT e.id FROM demo.events e LEFT JOIN demo.assets a ON e.asset_id = a.id OR 1=1', False),
    ('SELECT e.id FROM events e LEFT JOIN demo.assets a ON e.asset_id = a.id', False),
])
def test_preserve_source_policy(sql, allowed):
    assert validate_governed_join_policy(sql, REL).allowed is allowed


def test_matched_only_policy():
    sql = 'SELECT e.id FROM demo.events e INNER JOIN demo.assets a ON e.asset_id = a.id'
    assert validate_governed_join_policy(sql, {**REL, "join_policy": "matched_only"}).allowed


def test_unconfigured_policy_fails_closed():
    sql = 'SELECT e.id FROM demo.events e LEFT JOIN demo.assets a ON e.asset_id = a.id'
    assert not validate_governed_join_policy(sql, {**REL, "join_policy": "unconfigured"}).allowed


def test_many_to_many_policy_fails_closed():
    sql = 'SELECT e.id FROM demo.events e LEFT JOIN demo.assets a ON e.asset_id = a.id'
    assert not validate_governed_join_policy(sql, {**REL, "cardinality": "many_to_many"}).allowed
