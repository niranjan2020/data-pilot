from datapilot.application.services.query_correctness import assess_query_correctness


REL = {
    "name": "event_asset", "from_schema": "demo", "from_table": "demo.events",
    "from_column": "asset_id", "to_schema": "demo", "to_table": "demo.assets",
    "to_column": "id", "cardinality": "many_to_one",
    "join_policy": "preserve_source",
}


def checks(sql, rel=None):
    return assess_query_correctness(
        affected_tables=["demo.events", "demo.assets"],
        governed_tables=["demo.events", "demo.assets"],
        sql=sql, required_relationships=[rel or REL],
    )


def policy_status(sql, rel=None):
    return next(c["status"] for c in checks(sql, rel) if c["code"].startswith("join_policy_"))


def test_left_join_passes_governed_policy():
    sql = "SELECT e.id FROM demo.events e LEFT JOIN demo.assets a ON e.asset_id = a.id"
    assert policy_status(sql) == "passed"


def test_inner_join_fails_governed_policy():
    sql = "SELECT e.id FROM demo.events e INNER JOIN demo.assets a ON e.asset_id = a.id"
    assert policy_status(sql) == "failed"


def test_wrong_join_key_fails_governed_policy():
    sql = "SELECT e.id FROM demo.events e LEFT JOIN demo.assets a ON e.id = a.id"
    assert policy_status(sql) == "failed"


def test_unconfigured_join_fails_governed_policy():
    sql = "SELECT e.id FROM demo.events e LEFT JOIN demo.assets a ON e.asset_id = a.id"
    assert policy_status(sql, {**REL, "join_policy": "unconfigured"}) == "failed"
