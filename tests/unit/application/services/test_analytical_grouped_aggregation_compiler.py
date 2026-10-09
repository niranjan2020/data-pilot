import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan
from datapilot.application.services.analytical_sql_compiler import (
    GovernedMetricSource, compile_analytical_grouped_aggregation,
)


def fixture(*, metric_entity=1, dimension_entity=1, metric_table="OrderDetail",
            dimension_table="OrderDetail", aggregation="SUM", expression=None,
            order=("group", "aggregate"), group_extra=None):
    operations={
        "group":(AnalyticalOperation.GROUP,{"dimension":"OrderDetail.Region", **(group_extra or {})}),
        "aggregate":(AnalyticalOperation.AGGREGATE,{"metric":"Revenue"}),
    }
    steps=[]
    last="sales"
    for name in order:
        operation,parameters=operations[name]
        steps.append(PlanStep(name,operation,(last,),parameters))
        last=name
    plan=AnalyticalPlan(sources=("sales",),steps=tuple(steps),output=last)
    bound=bind_analytical_plan(plan,approved_metrics=[{"name":"Revenue"}],
        approved_dimensions=[{"name":"OrderDetail.Region"}])
    dimension=AnalyticalDimension("Region",dimension_entity,"OrderDetail","Sales",dimension_table,"RegionCode")
    metric={"name":"Revenue","entity_id":metric_entity,"attribute_name":"Amount",
            "aggregation":aggregation,"calculation_expression":expression}
    return unify_physical_analytical_plan(bound,published_dimensions=(dimension,),
        published_metrics=(metric,),published_time_dimensions=())


def source(**changes):
    values={"entity_id":1,"schema_name":"Sales","table_name":"OrderDetail","column_name":"Amount"}
    values.update(changes)
    return GovernedMetricSource(**values)


@pytest.mark.parametrize("function",["SUM","COUNT","AVG","MIN","MAX"])
def test_grouped_aggregation_compiles(function):
    sql=compile_analytical_grouped_aggregation(fixture(aggregation=function),metric_source=source()).sql
    assert sql==(
        f'SELECT "RegionCode" AS "dimension", {function}("Amount") AS "value" '
        'FROM "Sales"."OrderDetail" GROUP BY "RegionCode"'
    )


def test_cross_entity_grouping_rejected():
    with pytest.raises(ValueError,match="Cross-entity"):
        compile_analytical_grouped_aggregation(fixture(dimension_entity=2),metric_source=source())


def test_cross_table_grouping_rejected():
    with pytest.raises(ValueError,match="physical sources mismatch"):
        compile_analytical_grouped_aggregation(fixture(dimension_table="Customer"),metric_source=source())


def test_wrong_operation_order_rejected():
    with pytest.raises(ValueError,match="Unsupported"):
        compile_analytical_grouped_aggregation(fixture(order=("aggregate","group")),metric_source=source())


def test_extra_group_parameters_rejected():
    with pytest.raises(ValueError,match="requires one"):
        compile_analytical_grouped_aggregation(fixture(group_extra={"limit":10}),metric_source=source())


def test_calculated_metric_rejected():
    with pytest.raises(ValueError,match="Calculated"):
        compile_analytical_grouped_aggregation(fixture(expression="Amount * Quantity"),metric_source=source())


def test_metric_source_mismatch_rejected():
    with pytest.raises(ValueError,match="column mismatch"):
        compile_analytical_grouped_aggregation(fixture(),metric_source=source(column_name="Different"))


def test_unapproved_function_rejected():
    with pytest.raises(ValueError,match="Unsupported governed"):
        compile_analytical_grouped_aggregation(fixture(aggregation="MEDIAN"),metric_source=source())


def test_quoted_group_identifier_escaped():
    sql=compile_analytical_grouped_aggregation(fixture(dimension_table='Odd"Table'),metric_source=source(table_name='Odd"Table'))
    assert '"Odd""Table"' in sql.sql
