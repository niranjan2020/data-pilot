import pytest
from datapilot.application.services.analytical_evaluation import AnalyticalEvaluationCase
from datapilot.application.services.analytical_plan import AnalyticalOperation as Op
from datapilot.application.services.analytical_sql_semantic_evidence import verify_sql_semantics

@pytest.mark.parametrize("domain,sql,dimension,metric", [
    ("sales", "SELECT category, SUM(amount) FROM sales.orders GROUP BY category", "category", "SUM(amount)"),
    ("fleet", "SELECT operator, COUNT(id) FROM astra.vessels GROUP BY operator", "operator", "COUNT(id)"),
])
@pytest.mark.parametrize("variant", ["valid", "wrong_dimension", "wrong_metric", "unpublished_dimension", "unpublished_metric"])
def test_semantic_evidence(domain, sql, dimension, metric, variant):
    case = AnalyticalEvaluationCase(
        domain, "Group measure", (Op.GROUP, Op.AGGREGATE),
        expected_dimensions=("Group",), expected_metrics=("Measure",),
    )
    dims = {"Group": dimension}
    metrics = {"Measure": metric}
    if variant == "wrong_dimension":
        dims["Group"] = "other"
    if variant == "wrong_metric":
        metrics["Measure"] = "SUM(other)"
    if variant == "unpublished_dimension":
        dims.clear()
    if variant == "unpublished_metric":
        metrics.clear()
    result = verify_sql_semantics(case, sql, dimension_columns=dims, metric_expressions=metrics)
    assert not result.verified
    assert result.failures
    if variant == "valid":
        assert result.failures == ("result_correctness_not_verified",)
    else:
        assert any("mismatch" in reason or "unpublished" in reason for reason in result.failures)

@pytest.mark.parametrize("sql,reason", [
    ("SELECT category, COUNT(id) FROM items GROUP BY category HAVING COUNT(id)>1", "complex_sql_requires_governed_plan"),
    ("SELECT a.id FROM a JOIN b ON a.id=b.id", "complex_sql_requires_governed_plan"),
    ("SELECT id FROM items WHERE color='red'", "filter_values_not_verified"),
    ("SELECT id FROM items LIMIT 10", "limit_value_not_verified"),
    ("SELECT id FROM items ORDER BY id", "sort_semantics_not_verified"),
    ("DELETE FROM items", "unsupported_statement"),
    ("", "sql_missing"),
])
def test_unverified_capabilities(sql, reason):
    case = AnalyticalEvaluationCase("test", "Question", (Op.PROJECT,))
    result = verify_sql_semantics(case, sql, dimension_columns={}, metric_expressions={})
    assert not result.verified
    assert reason in result.failures

@pytest.mark.parametrize("invalid", [None, [], "untrusted"])
def test_invalid_bindings_fail_closed(invalid):
    case = AnalyticalEvaluationCase("test", "Question", (Op.PROJECT,))
    with pytest.raises(ValueError, match="bindings"):
        verify_sql_semantics(case, "SELECT id FROM items", dimension_columns=invalid, metric_expressions={})
