from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.application.services.query_correctness import assess_query_correctness


def context(policy="preserve_source"):
    return {
        "entities": [
            {"id": 1, "schema_name": "demo", "table_name": "events"},
            {"id": 2, "schema_name": "demo", "table_name": "assets"},
        ],
        "relationships": [{
            "name": "event_asset", "from_entity_id": 1, "to_entity_id": 2,
            "from_column": "asset_id", "to_column": "id",
            "cardinality": "many_to_one", "join_policy": policy,
        }],
    }


def test_published_policy_survives_runtime_mapping():
    relationships = QueryOrchestrator._required_relationships(context())
    assert len(relationships) == 1
    assert relationships[0]["join_policy"] == "preserve_source"
    assert relationships[0]["from_schema"] == "demo"
    assert relationships[0]["to_schema"] == "demo"


def test_mapped_policy_rejects_inner_join():
    sql = "SELECT e.id FROM demo.events e INNER JOIN demo.assets a ON e.asset_id = a.id"
    checks = assess_query_correctness(
        affected_tables=["demo.events", "demo.assets"],
        governed_tables=["demo.events", "demo.assets"],
        sql=sql, required_relationships=QueryOrchestrator._required_relationships(context()),
    )
    assert any(c["code"] == "join_policy_violation" and c["status"] == "failed" for c in checks)


def test_mapped_policy_accepts_left_join():
    sql = "SELECT e.id FROM demo.events e LEFT JOIN demo.assets a ON e.asset_id = a.id"
    checks = assess_query_correctness(
        affected_tables=["demo.events", "demo.assets"],
        governed_tables=["demo.events", "demo.assets"],
        sql=sql, required_relationships=QueryOrchestrator._required_relationships(context()),
    )
    assert any(c["code"] == "join_policy_alignment" and c["status"] == "passed" for c in checks)


def test_unconfigured_published_policy_fails_closed():
    sql = "SELECT e.id FROM demo.events e LEFT JOIN demo.assets a ON e.asset_id = a.id"
    checks = assess_query_correctness(
        affected_tables=["demo.events", "demo.assets"],
        governed_tables=["demo.events", "demo.assets"],
        sql=sql, required_relationships=QueryOrchestrator._required_relationships(context("unconfigured")),
    )
    assert any(c["code"] == "join_policy_violation" and c["status"] == "failed" for c in checks)


def test_legacy_relationship_does_not_gain_invented_policy():
    legacy = context()
    del legacy["relationships"][0]["join_policy"]
    relationships = QueryOrchestrator._required_relationships(legacy)
    assert "join_policy" not in relationships[0]
