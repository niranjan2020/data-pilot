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


def test_metric_lineage_matches_declared_physical_source():
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    result = checks(SQL, metric)
    assert any(item["code"] == "metric_lineage_alignment" for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_metric_lineage_rejects_wrong_source_table():
    metric = {**METRIC, "table_name": "demo.children", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(SQL, metric))


def test_metric_lineage_rejects_wrong_source_column():
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "other_amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(SQL, metric))


def test_metric_lineage_without_physical_metadata_is_not_guessed():
    assert not any(item["code"].startswith("metric_lineage_") for item in checks(SQL))


def test_metric_lineage_rejects_same_table_name_in_wrong_schema():
    metric = {**METRIC, "table_name": "other.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(SQL, metric))


def test_metric_lineage_accepts_explicit_schema_qualified_source():
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_alignment" for item in checks(SQL, metric))


def test_metric_lineage_does_not_accept_nonaggregated_source_column():
    sql = SQL.replace("SUM(p.amount)", "COUNT(*)")
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_metric_lineage_does_not_accept_unqualified_aggregate_column():
    sql = SQL.replace("SUM(p.amount)", "SUM(amount)")
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_metric_lineage_reused_alias_in_nested_scope_is_unverified():
    sql = (
        "SELECT SUM(p.amount), (SELECT SUM(p.amount) FROM demo.children p) AS child_total "
        "FROM demo.parents p"
    )
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_metric_lineage_distinct_aliases_remain_verifiable():
    sql = (
        "SELECT SUM(p.amount), (SELECT COUNT(*) FROM demo.children c) AS child_total "
        "FROM demo.parents p"
    )
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_alignment" for item in checks(sql, metric))


def test_metric_lineage_reused_alias_does_not_waive_fanout():
    sql = (
        "SELECT SUM(p.amount), (SELECT SUM(p.amount) FROM demo.children p) AS child_total "
        "FROM demo.parents p JOIN demo.children c ON p.id = c.parent_id"
    )
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    result = checks(sql, metric)
    assert any(item["code"] == "metric_lineage_unverified" for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_scope_aware_lineage_allows_reused_alias_with_unrelated_column():
    sql = (
        "SELECT SUM(p.amount), (SELECT COUNT(*) FROM demo.children p) AS n "
        "FROM demo.parents p"
    )
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_alignment" for item in checks(sql, metric))


def test_scope_aware_lineage_rejects_nested_wrong_source_aggregate():
    sql = (
        "SELECT SUM(p.amount), (SELECT SUM(p.amount) FROM demo.children p) AS n "
        "FROM demo.parents p"
    )
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_scope_aware_lineage_rejects_same_alias_wrong_schema():
    sql = "SELECT SUM(p.amount) FROM other.parents p"
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_lineage_traces_simple_derived_table_projection():
    sql = "SELECT SUM(d.amount) FROM (SELECT p.amount FROM demo.parents p) d"
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_alignment" for item in checks(sql, metric))


def test_lineage_rejects_derived_projection_from_wrong_schema():
    sql = "SELECT SUM(d.amount) FROM (SELECT p.amount FROM other.parents p) d"
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_lineage_rejects_derived_expression_projection():
    sql = "SELECT SUM(d.amount) FROM (SELECT p.amount * 2 AS amount FROM demo.parents p) d"
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_lineage_rejects_joined_derived_projection():
    sql = (
        "SELECT SUM(d.amount) FROM (SELECT p.amount FROM demo.parents p "
        "JOIN demo.children c ON p.id = c.parent_id) d"
    )
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_lineage_traces_renamed_derived_metric_projection():
    sql = "SELECT SUM(d.total_value) FROM (SELECT p.amount AS total_value FROM demo.parents p) d"
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_alignment" for item in checks(sql, metric))


def test_lineage_rejects_renamed_projection_from_wrong_column():
    sql = "SELECT SUM(d.total_value) FROM (SELECT p.other_amount AS total_value FROM demo.parents p) d"
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_lineage_rejects_renamed_projection_from_wrong_table():
    sql = "SELECT SUM(d.total_value) FROM (SELECT p.amount AS total_value FROM demo.children p) d"
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_lineage_rejects_mixed_derived_aggregate_inputs():
    sql = (
        "SELECT SUM(d.total_value) + SUM(d.other_value) "
        "FROM (SELECT p.amount AS total_value, p.other_amount AS other_value FROM demo.parents p) d"
    )
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_lineage_does_not_certify_mixed_direct_aggregate_expression():
    sql = "SELECT SUM(p.amount + p.other_amount) FROM demo.parents p"
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_lineage_does_not_certify_two_distinct_aggregate_sources():
    sql = "SELECT SUM(p.amount), SUM(p.other_amount) FROM demo.parents p"
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_lineage_keeps_direct_metric_with_unrelated_count_star():
    sql = "SELECT SUM(p.amount), COUNT(*) FROM demo.parents p"
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_alignment" for item in checks(sql, metric))


def test_lineage_rejects_transformed_direct_metric():
    sql = "SELECT SUM(ABS(p.amount)) FROM demo.parents p"
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    assert any(item["code"] == "metric_lineage_unverified" for item in checks(sql, metric))


def test_risky_relationship_reports_confirmed_metric_ownership():
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    result = checks(SQL, metric)
    assert any(item["code"] == "fanout_metric_ownership_confirmed" for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_risky_relationship_reports_unverified_metric_ownership():
    metric = {**METRIC, "table_name": "demo.children", "column_name": "amount"}
    result = checks(SQL, metric)
    assert any(item["code"] == "fanout_metric_ownership_unverified" for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_risky_relationship_without_physical_metadata_keeps_existing_violation():
    result = checks(SQL)
    assert not any(item["code"].startswith("fanout_metric_ownership_") for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_count_distinct_does_not_emit_risky_metric_ownership_check():
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "id", "aggregation": "count_distinct"}
    sql = SQL.replace("SUM(p.amount)", "COUNT(DISTINCT p.id)")
    result = checks(sql, metric)
    assert not any(item["code"].startswith("fanout_metric_ownership_") for item in result)
