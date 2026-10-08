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


def test_fanout_proof_obligations_report_confirmed_lineage_and_grain():
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    result = checks(SQL, metric)
    evidence = next(item for item in result if item["code"] == "fanout_safety_evidence_incomplete")
    assert evidence["metric_ownership_verified"] is True
    assert evidence["preaggregation_grain_verified"] is True
    assert evidence["join_cardinality_safe"] is False
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_fanout_proof_obligations_reject_unverified_metric_ownership():
    metric = {**METRIC, "table_name": "demo.children", "column_name": "amount"}
    evidence = next(item for item in checks(SQL, metric) if item["code"] == "fanout_safety_evidence_incomplete")
    assert evidence["metric_ownership_verified"] is False
    assert evidence["join_cardinality_safe"] is False


def test_fanout_proof_obligations_reject_unverified_grain():
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "amount"}
    sql = "SELECT SUM(p.amount) FROM demo.parents p JOIN demo.children c ON p.id = c.parent_id"
    evidence = next(item for item in checks(sql, metric) if item["code"] == "fanout_safety_evidence_incomplete")
    assert evidence["preaggregation_grain_verified"] is False
    assert evidence["join_cardinality_safe"] is False


def test_fanout_proof_obligations_not_emitted_for_count_distinct():
    metric = {**METRIC, "table_name": "demo.parents", "column_name": "id", "aggregation": "count_distinct"}
    sql = SQL.replace("SUM(p.amount)", "COUNT(DISTINCT p.id)")
    assert not any(item["code"] == "fanout_safety_evidence_incomplete" for item in checks(sql, metric))


def test_fanout_join_grain_key_observed_for_grouped_derived_join():
    evidence = next(item for item in checks(SQL) if item["code"] == "fanout_join_grain_key_observed")
    assert evidence["joined_grain_keys"] == ["c.parent_id"]
    assert any(item["code"] == "join_fanout_violation" for item in checks(SQL))


def test_fanout_join_grain_key_unverified_for_direct_join():
    sql = "SELECT SUM(p.amount) FROM demo.parents p JOIN demo.children c ON p.id = c.parent_id"
    assert any(item["code"] == "fanout_join_grain_key_unverified" for item in checks(sql))


def test_fanout_join_grain_key_unverified_for_non_equality_join():
    sql = (
        "SELECT SUM(p.amount) FROM demo.parents p "
        "JOIN (SELECT parent_id, COUNT(*) AS n FROM demo.children GROUP BY parent_id) c "
        "ON p.id > c.parent_id"
    )
    assert any(item["code"] == "fanout_join_grain_key_unverified" for item in checks(sql))


def test_fanout_join_grain_key_unverified_when_join_uses_non_grouped_projection():
    sql = (
        "SELECT SUM(p.amount) FROM demo.parents p "
        "JOIN (SELECT parent_id, MAX(id) AS other_id FROM demo.children GROUP BY parent_id) c "
        "ON p.id = c.other_id"
    )
    assert any(item["code"] == "fanout_join_grain_key_unverified" for item in checks(sql))


def test_join_coverage_observed_for_single_simple_derived_join():
    result = checks(SQL)
    evidence = next(item for item in result if item["code"] == "fanout_join_coverage_observed")
    assert evidence["outer_join_count"] == 1
    assert evidence["observed_grain_key_count"] == 1
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_join_coverage_incomplete_with_additional_direct_join():
    sql = SQL.replace(" GROUP BY p.id", " JOIN demo.children extra ON extra.parent_id = p.id GROUP BY p.id")
    result = checks(sql)
    assert any(item["code"] == "fanout_join_coverage_incomplete" for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_join_coverage_incomplete_for_direct_join_only():
    sql = "SELECT SUM(p.amount) FROM demo.parents p JOIN demo.children c ON p.id = c.parent_id"
    assert any(item["code"] == "fanout_join_coverage_incomplete" for item in checks(sql))


def test_join_coverage_incomplete_for_non_equality_derived_join():
    sql = SQL.replace("ON p.id = c.parent_id", "ON p.id > c.parent_id")
    assert any(item["code"] == "fanout_join_coverage_incomplete" for item in checks(sql))


def test_nested_derived_join_does_not_count_as_outer_grain_evidence():
    sql = (
        "SELECT SUM(p.amount) FROM demo.parents p "
        "JOIN (SELECT x.parent_id FROM demo.children x "
        "JOIN (SELECT parent_id, COUNT(*) AS n FROM demo.children GROUP BY parent_id) y "
        "ON x.parent_id = y.parent_id) d ON p.id = d.parent_id"
    )
    result = checks(sql)
    coverage = next(item for item in result if item["code"] == "fanout_join_coverage_incomplete")
    assert coverage["outer_join_count"] == 1
    assert coverage["observed_grain_key_count"] == 0


def test_nested_derived_join_does_not_report_outer_grain_key():
    sql = (
        "SELECT SUM(p.amount) FROM demo.parents p "
        "JOIN (SELECT x.parent_id FROM demo.children x "
        "JOIN (SELECT parent_id, COUNT(*) AS n FROM demo.children GROUP BY parent_id) y "
        "ON x.parent_id = y.parent_id) d ON p.id = d.parent_id"
    )
    result = checks(sql)
    assert any(item["code"] == "fanout_join_grain_key_unverified" for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_outer_grain_key_remains_observed_with_scalar_nested_join():
    sql = (
        "SELECT SUM(p.amount), "
        "(SELECT COUNT(*) FROM demo.children x JOIN demo.parents y ON x.parent_id = y.id) AS n "
        "FROM demo.parents p "
        "JOIN (SELECT parent_id, COUNT(*) AS n FROM demo.children GROUP BY parent_id) c "
        "ON p.id = c.parent_id"
    )
    result = checks(sql)
    coverage = next(item for item in result if item["code"] == "fanout_join_coverage_observed")
    assert coverage["outer_join_count"] == 1
    assert coverage["observed_grain_key_count"] == 1


def test_governed_relationship_keys_match_direct_sql_equality():
    relationship = {**RELATIONSHIP, "from_schema": "demo", "from_table": "parents",
                    "from_column": "id", "to_schema": "demo",
                    "to_table": "children", "to_column": "parent_id"}
    sql = "SELECT SUM(p.amount) FROM demo.parents p JOIN demo.children c ON p.id = c.parent_id"
    result = assess_query_correctness(
        sql=sql, affected_tables=["demo.parents", "demo.children"],
        governed_tables=["demo.parents", "demo.children"],
        governed_metrics=[METRIC], required_relationships=[relationship])
    assert any(item["code"] == "fanout_relationship_keys_matched" for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_governed_relationship_keys_reject_wrong_join_column():
    relationship = {**RELATIONSHIP, "from_schema": "demo", "from_table": "parents",
                    "from_column": "id", "to_schema": "demo",
                    "to_table": "children", "to_column": "parent_id"}
    sql = "SELECT SUM(p.amount) FROM demo.parents p JOIN demo.children c ON p.id = c.other_id"
    result = assess_query_correctness(
        sql=sql, affected_tables=["demo.parents", "demo.children"],
        governed_tables=["demo.parents", "demo.children"],
        governed_metrics=[METRIC], required_relationships=[relationship])
    assert any(item["code"] == "fanout_relationship_keys_unverified" for item in result)


def test_governed_relationship_keys_reject_missing_key_metadata():
    sql = "SELECT SUM(p.amount) FROM demo.parents p JOIN demo.children c ON p.id = c.parent_id"
    assert any(item["code"] == "fanout_relationship_keys_unverified" for item in checks(sql))


def test_governed_relationship_keys_reject_wrong_schema():
    relationship = {**RELATIONSHIP, "from_schema": "other", "from_table": "parents",
                    "from_column": "id", "to_schema": "demo",
                    "to_table": "children", "to_column": "parent_id"}
    sql = "SELECT SUM(p.amount) FROM demo.parents p JOIN demo.children c ON p.id = c.parent_id"
    result = assess_query_correctness(
        sql=sql, affected_tables=["demo.parents", "demo.children"],
        governed_tables=["demo.parents", "demo.children"],
        governed_metrics=[METRIC], required_relationships=[relationship])
    assert any(item["code"] == "fanout_relationship_keys_unverified" for item in result)


def _relationship_key_checks(sql):
    relationship = {**RELATIONSHIP, "from_schema": "demo", "from_table": "parents",
                    "from_column": "id", "to_schema": "demo",
                    "to_table": "children", "to_column": "parent_id"}
    return assess_query_correctness(
        sql=sql, affected_tables=["demo.parents", "demo.children"],
        governed_tables=["demo.parents", "demo.children"],
        governed_metrics=[METRIC], required_relationships=[relationship])


def test_relationship_key_match_rejects_repeated_source_table():
    sql = (
        "SELECT SUM(p.amount) FROM demo.parents p "
        "JOIN demo.children c ON p.id = c.parent_id "
        "JOIN demo.parents p2 ON p2.id = c.parent_id"
    )
    result = _relationship_key_checks(sql)
    assert any(item["code"] == "fanout_relationship_keys_unverified" for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_relationship_key_match_rejects_repeated_target_table():
    sql = (
        "SELECT SUM(p.amount) FROM demo.parents p "
        "JOIN demo.children c ON p.id = c.parent_id "
        "JOIN demo.children c2 ON p.id = c2.parent_id"
    )
    assert any(item["code"] == "fanout_relationship_keys_unverified" for item in _relationship_key_checks(sql))


def test_relationship_key_match_allows_unrelated_distinct_table():
    sql = (
        "SELECT SUM(p.amount) FROM demo.parents p "
        "JOIN demo.children c ON p.id = c.parent_id "
        "JOIN demo.categories cat ON cat.id = p.category_id"
    )
    result = _relationship_key_checks(sql)
    assert any(item["code"] == "fanout_relationship_keys_matched" for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_derived_grouping_key_uniqueness_observed_without_waiving_fanout():
    result = checks(SQL)
    evidence = next(item for item in result if item["code"] == "fanout_derived_key_uniqueness_observed")
    assert evidence["unique_derived_join_keys"] == ["c.parent_id"]
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_derived_key_uniqueness_unverified_for_direct_join():
    sql = "SELECT SUM(p.amount) FROM demo.parents p JOIN demo.children c ON p.id = c.parent_id"
    assert any(item["code"] == "fanout_derived_key_uniqueness_unverified" for item in checks(sql))


def test_derived_key_uniqueness_unverified_for_nested_join():
    sql = (
        "SELECT SUM(p.amount) FROM demo.parents p "
        "JOIN (SELECT c.parent_id, COUNT(*) AS n FROM demo.children c "
        "JOIN demo.parents x ON x.id = c.parent_id GROUP BY c.parent_id) d "
        "ON p.id = d.parent_id"
    )
    assert any(item["code"] == "fanout_derived_key_uniqueness_unverified" for item in checks(sql))


def test_derived_key_uniqueness_unverified_with_limit():
    sql = SQL.replace("GROUP BY parent_id)", "GROUP BY parent_id LIMIT 1)")
    assert any(item["code"] == "fanout_derived_key_uniqueness_unverified" for item in checks(sql))


def _governed_derived_checks(sql):
    relationship = {**RELATIONSHIP, "from_schema": "demo", "from_table": "parents",
                    "from_column": "id", "to_schema": "demo",
                    "to_table": "children", "to_column": "parent_id"}
    return assess_query_correctness(
        sql=sql, affected_tables=["demo.parents", "demo.children"],
        governed_tables=["demo.parents", "demo.children"],
        governed_metrics=[METRIC], required_relationships=[relationship])


def test_governed_derived_unique_key_matches_physical_relationship():
    result = _governed_derived_checks(SQL)
    evidence = next(item for item in result if item["code"] == "fanout_governed_derived_uniqueness_observed")
    assert evidence["governed_derived_join_keys"] == ["p.id=c.parent_id"]
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_governed_derived_unique_key_rejects_wrong_physical_source():
    sql = SQL.replace("FROM demo.children", "FROM demo.categories")
    assert any(item["code"] == "fanout_governed_derived_uniqueness_unverified"
               for item in _governed_derived_checks(sql))


def test_governed_derived_unique_key_rejects_wrong_join_column():
    sql = SQL.replace("ON p.id = c.parent_id", "ON p.other_id = c.parent_id")
    assert any(item["code"] == "fanout_governed_derived_uniqueness_unverified"
               for item in _governed_derived_checks(sql))


def test_governed_derived_unique_key_rejects_missing_metadata():
    assert any(item["code"] == "fanout_governed_derived_uniqueness_unverified"
               for item in checks(SQL))


def test_graph_uniqueness_observed_for_single_governed_derived_join():
    result = _governed_derived_checks(SQL)
    evidence = next(item for item in result if item["code"] == "fanout_join_graph_uniqueness_observed")
    assert evidence["outer_join_count"] == 1
    assert evidence["unique_derived_edge_count"] == 1
    assert any(item["code"] == "join_fanout_violation" for item in result)


def test_graph_uniqueness_incomplete_for_additional_direct_join():
    sql = SQL.replace(" GROUP BY p.id", " JOIN demo.children extra ON extra.parent_id = p.id GROUP BY p.id")
    assert any(item["code"] == "fanout_join_graph_uniqueness_incomplete"
               for item in _governed_derived_checks(sql))


def test_graph_uniqueness_incomplete_without_governed_metadata():
    assert any(item["code"] == "fanout_join_graph_uniqueness_incomplete" for item in checks(SQL))


def test_graph_uniqueness_incomplete_for_duplicate_derived_alias():
    sql = (
        "SELECT SUM(p.amount) FROM demo.parents p "
        "JOIN (SELECT parent_id FROM demo.children GROUP BY parent_id) c ON p.id = c.parent_id "
        "JOIN (SELECT parent_id FROM demo.children GROUP BY parent_id) c ON p.id = c.parent_id"
    )
    assert any(item["code"] == "fanout_join_graph_uniqueness_incomplete"
               for item in _governed_derived_checks(sql))


# Batch regression matrix: each parametrized scenario is a separate pytest case.
@pytest.mark.parametrize(
    "join_sql,expected_supported",
    [
        ("JOIN demo.children c ON p.id = c.parent_id", True),
        ("INNER JOIN demo.children c ON p.id = c.parent_id", True),
        ("LEFT JOIN demo.children c ON p.id = c.parent_id", True),
        ("LEFT OUTER JOIN demo.children c ON p.id = c.parent_id", True),
        ("RIGHT JOIN demo.children c ON p.id = c.parent_id", False),
        ("RIGHT OUTER JOIN demo.children c ON p.id = c.parent_id", False),
        ("FULL JOIN demo.children c ON p.id = c.parent_id", False),
        ("FULL OUTER JOIN demo.children c ON p.id = c.parent_id", False),
        ("CROSS JOIN demo.children c", False),
        ("JOIN demo.children c ON p.id > c.parent_id", False),
        ("JOIN demo.children c ON p.id < c.parent_id", False),
        ("JOIN demo.children c ON p.id <> c.parent_id", False),
    ],
)
def test_join_type_cardinality_review_matrix(join_sql, expected_supported):
    sql = f"SELECT SUM(p.amount) FROM demo.parents p {join_sql}"
    result = checks(sql)
    expected = "fanout_join_types_supported" if expected_supported else "fanout_join_types_unverified"
    assert any(item["code"] == expected for item in result)
    assert any(item["code"] == "join_fanout_violation" for item in result)


@pytest.mark.parametrize(
    "join_clause",
    [
        "JOIN demo.children c ON p.id = c.parent_id",
        "LEFT JOIN demo.children c ON p.id = c.parent_id",
        "RIGHT JOIN demo.children c ON p.id = c.parent_id",
        "FULL JOIN demo.children c ON p.id = c.parent_id",
        "CROSS JOIN demo.children c",
        "JOIN demo.children c ON p.id > c.parent_id",
        "JOIN demo.children c ON p.id < c.parent_id",
        "JOIN demo.children c ON p.id <> c.parent_id",
    ],
)
def test_fanout_violation_never_waived_by_join_type(join_clause):
    sql = f"SELECT SUM(p.amount) FROM demo.parents p {join_clause}"
    result = checks(sql)
    assert any(item["code"] == "join_fanout_violation" and item["status"] == "failed"
               for item in result)
    assert any(item["code"] == "fanout_safety_evidence_incomplete"
               and item["join_cardinality_safe"] is False for item in result)
