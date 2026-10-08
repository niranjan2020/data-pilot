"""Pre-aggregation must not bypass governed metric fan-out checks."""
import pytest

from datapilot.application.services.query_correctness import assess_query_correctness


METRIC = {"name": "amount", "entity_id": 10, "aggregation": "sum"}
RELATIONSHIP = {
    "name": "parent_children",
    "from_entity_id": 10, "to_entity_id": 20,
    "cardinality": "one_to_many",
}
SQL = (
    "SELECT p.id, SUM(p.amount) FROM demo.parents p "
    "JOIN (SELECT parent_id, COUNT(*) AS n FROM demo.children GROUP BY parent_id) c "
    "ON p.id = c.parent_id GROUP BY p.id"
)


def checks(sql, metric=METRIC):
    return assess_query_correctness(
        sql=sql,
        affected_tables=["demo.parents", "demo.children"],
        governed_tables=["demo.parents", "demo.children"],
        governed_metrics=[metric],
        required_relationships=[RELATIONSHIP],
    )


def test_preaggregation_does_not_silence_fanout_violation():
    result = checks(SQL)
    assert any(item["code"] == "join_fanout_violation" and item["status"] == "failed" for item in result)


def test_preaggregation_does_not_claim_unverified_fanout_safety():
    result = checks(SQL)
    assert not any(item["code"] == "fanout_verification_unavailable" for item in result)


def test_count_distinct_retains_existing_safe_exception():
    result = checks(SQL.replace("SUM(p.amount)", "COUNT(DISTINCT p.id)"),
                    {**METRIC, "aggregation": "count_distinct"})
    assert not any(item["code"] == "join_fanout_violation" for item in result)


def test_direct_risky_join_still_fails():
    sql = ("SELECT p.id, SUM(p.amount) FROM demo.parents p "
           "JOIN demo.children c ON p.id = c.parent_id GROUP BY p.id")
    assert any(item["code"] == "join_fanout_violation" for item in checks(sql))
