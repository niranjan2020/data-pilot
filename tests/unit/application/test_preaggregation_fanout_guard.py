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


def test_preaggregation_reports_join_key_grain():
    result = checks(SQL)
    assert any(item["code"] == "preaggregation_grain_alignment" for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_preaggregation_rejects_wrong_grouping_grain():
    sql = SQL.replace("GROUP BY parent_id", "GROUP BY category_id")
    result = checks(sql)
    assert any(item["code"] == "preaggregation_grain_unverified" for item in result)


def test_preaggregation_accepts_projected_key_alias():
    sql = SQL.replace("SELECT parent_id, COUNT(*)", "SELECT parent_id AS parent_key, COUNT(*)").replace("c.parent_id", "c.parent_key")
    result = checks(sql)
    assert any(item["code"] == "preaggregation_grain_alignment" for item in result)


def test_preaggregation_requires_single_grouping_key():
    sql = SQL.replace("GROUP BY parent_id", "GROUP BY parent_id, category_id")
    result = checks(sql)
    assert any(item["code"] == "preaggregation_grain_unverified" for item in result)


def test_each_derived_aggregation_join_receives_own_grain_check():
    sql = (
        "SELECT p.id, SUM(p.amount) FROM demo.parents p "
        "JOIN (SELECT parent_id, COUNT(*) AS n FROM demo.children GROUP BY parent_id) c "
        "ON p.id = c.parent_id "
        "JOIN (SELECT parent_id, COUNT(*) AS n FROM demo.events GROUP BY category_id) e "
        "ON p.id = e.parent_id GROUP BY p.id"
    )
    result = checks(sql)
    grain = [item["code"] for item in result if item["code"].startswith("preaggregation_grain_")]
    assert grain == ["preaggregation_grain_alignment", "preaggregation_grain_unverified"]
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_nested_join_cannot_prove_derived_table_grain():
    sql = SQL.replace(
        "FROM demo.children GROUP BY parent_id",
        "FROM demo.children ch JOIN demo.events ev ON ch.parent_id = ev.parent_id GROUP BY parent_id",
    )
    result = checks(sql)
    assert any(item["code"] == "preaggregation_grain_unverified" for item in result)


def test_unrelated_scalar_aggregation_not_reported_as_join_grain():
    sql = (
        "SELECT p.id, (SELECT COUNT(*) FROM demo.children) AS total "
        "FROM demo.parents p JOIN demo.children c ON p.id = c.parent_id"
    )
    result = checks(sql)
    assert not any(item["code"].startswith("preaggregation_grain_") for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_limited_derived_aggregation_cannot_certify_grain():
    sql = SQL.replace("GROUP BY parent_id)", "GROUP BY parent_id LIMIT 10)")
    result = checks(sql)
    assert any(item["code"] == "preaggregation_grain_unverified" for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_offset_derived_aggregation_cannot_certify_grain():
    sql = SQL.replace("GROUP BY parent_id)", "GROUP BY parent_id OFFSET 5)")
    assert any(item["code"] == "preaggregation_grain_unverified" for item in checks(sql))


def test_windowed_derived_aggregation_cannot_certify_grain():
    sql = SQL.replace(
        "COUNT(*) AS n",
        "COUNT(*) AS n, ROW_NUMBER() OVER (ORDER BY parent_id) AS row_num",
    )
    assert any(item["code"] == "preaggregation_grain_unverified" for item in checks(sql))


def test_plain_grouped_derived_aggregation_remains_proven():
    assert any(item["code"] == "preaggregation_grain_alignment" for item in checks(SQL))
