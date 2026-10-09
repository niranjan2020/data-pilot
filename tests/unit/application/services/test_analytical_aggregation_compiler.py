import pytest

from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan
from datapilot.application.services.analytical_sql_compiler import (
    GovernedMetricSource, compile_analytical_aggregation,
)


def fixture(*, aggregation="SUM", expression=None, attribute="Amount", operation=AnalyticalOperation.AGGREGATE):
    plan=AnalyticalPlan(sources=("sales",),steps=(
        PlanStep("aggregate",operation,("sales",),{"metric":"Revenue"}),
    ),output="aggregate")
    bound=bind_analytical_plan(plan,approved_metrics=[{"name":"Revenue"}],approved_dimensions=[])
    return unify_physical_analytical_plan(bound,published_dimensions=(),
        published_metrics=({"name":"Revenue","entity_id":1,"attribute_name":attribute,
                            "aggregation":aggregation,"calculation_expression":expression},),
        published_time_dimensions=())


def source(**kwargs):
    fields={"entity_id":1,"schema_name":"Sales","table_name":"OrderDetail","column_name":"Amount"}
    fields.update(kwargs)
    return GovernedMetricSource(**fields)


@pytest.mark.parametrize("function",["SUM","COUNT","AVG","MIN","MAX"])
def test_supported_aggregations_are_deterministic(function):
    result=compile_analytical_aggregation(fixture(aggregation=function),metric_source=source())
    assert result.sql==f'SELECT {function}("Amount") AS "value" FROM "Sales"."OrderDetail"'


def test_metric_source_entity_must_match():
    with pytest.raises(ValueError,match="entity mismatch"):
        compile_analytical_aggregation(fixture(),metric_source=source(entity_id=2))


def test_metric_source_column_must_match():
    with pytest.raises(ValueError,match="column mismatch"):
        compile_analytical_aggregation(fixture(),metric_source=source(column_name="Other"))


def test_expression_is_rejected_until_validated():
    with pytest.raises(ValueError,match="Calculated"):
        compile_analytical_aggregation(fixture(expression="Amount * Quantity"),metric_source=source())


def test_unsupported_aggregation_is_rejected():
    with pytest.raises(ValueError,match="Unsupported governed"):
        compile_analytical_aggregation(fixture(aggregation="STRING_AGG"),metric_source=source())


def test_unsupported_operation_is_rejected():
    with pytest.raises(ValueError,match="Unsupported analytical"):
        compile_analytical_aggregation(fixture(operation=AnalyticalOperation.SORT),metric_source=source())


def test_identifier_quotes_are_escaped():
    result=compile_analytical_aggregation(fixture(),metric_source=source(table='Odd"Table'))
    assert '"Odd""Table"' in result.sql


def test_invalid_metric_source_is_rejected():
    with pytest.raises(ValueError,match="Governed metric source"):
        compile_analytical_aggregation(fixture(),metric_source=None)
