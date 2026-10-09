import pytest
from datapilot.application.services.analytical_evaluation import AnalyticalEvaluationCase
from datapilot.application.services.analytical_plan import AnalyticalOperation as Op
from datapilot.application.services.analytical_sql_observation import AnalyticalSQLObservation
from datapilot.application.services.analytical_sql_comparison import compare_golden_sql_structure, StructuralDisposition

@pytest.mark.parametrize("source", ["sales.orders", "sales.other", "orders"])
@pytest.mark.parametrize("operations", [(Op.GROUP, Op.AGGREGATE, Op.SORT, Op.LIMIT), (Op.FILTER,), ()])
def test_comparison(source, operations):
    gold = AnalyticalEvaluationCase("case", "Top categories", (Op.GROUP, Op.AGGREGATE, Op.SORT, Op.LIMIT), expected_source=("sales", "orders"))
    observed = AnalyticalSQLObservation("case", operations, (source,), True, ("semantic_binding_not_verified",))
    result = compare_golden_sql_structure(gold, observed)
    assert not result.semantic_verified
    if source == "sales.orders" and operations == gold.expected_operations:
        assert result.disposition is StructuralDisposition.MATCH
    else:
        assert result.disposition is not StructuralDisposition.MATCH
