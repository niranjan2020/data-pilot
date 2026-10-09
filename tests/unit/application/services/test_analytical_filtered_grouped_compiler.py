import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan
from datapilot.application.services.analytical_sql_compiler import (
    GovernedMetricSource, compile_analytical_filtered_grouped_limit,
)

DIMENSIONS=(
    AnalyticalDimension("Status",1,"OrderDetail","Sales","OrderDetail","StatusCode"),
    AnalyticalDimension("Region",1,"OrderDetail","Sales","OrderDetail","RegionCode"),
)


def build(*, values=("O","T","TO"),operator="IN",filter_dimension="OrderDetail.Status",
          filter_table="OrderDetail",limit=5):
    plan=AnalyticalPlan(sources=("sales",),steps=(
        PlanStep("filter",AnalyticalOperation.FILTER,("sales",),
                 {"dimension":filter_dimension,"operator":operator,"values":values}),
        PlanStep("group",AnalyticalOperation.GROUP,("filter",),{"dimension":"OrderDetail.Region"}),
        PlanStep("aggregate",AnalyticalOperation.AGGREGATE,("group",),{"metric":"Revenue"}),
        PlanStep("sort",AnalyticalOperation.SORT,("aggregate",),{"metric":"Revenue","direction":"DESC"}),
        PlanStep("limit",AnalyticalOperation.LIMIT,("sort",),{"count":limit}),
    ),output="limit")
    bound=bind_analytical_plan(plan,approved_dimensions=[
        {"name":"OrderDetail.Status"},{"name":"OrderDetail.Region"}
    ],approved_metrics=[{"name":"Revenue"}])
    physical=unify_physical_analytical_plan(
        bound,published_dimensions=DIMENSIONS,
        published_metrics=({"name":"Revenue","entity_id":1,"attribute_name":"Amount",
                            "aggregation":"SUM","calculation_expression":None},),
        published_time_dimensions=(),
    )
    approved=DIMENSIONS if filter_table=="OrderDetail" else (
        AnalyticalDimension("Status",1,"OrderDetail","Sales",filter_table,"StatusCode"),
        DIMENSIONS[1],
    )
    return physical,approved


def compile(**kwargs):
    plan,dimensions=build(**kwargs)
    return compile_analytical_filtered_grouped_limit(
        plan,metric_source=GovernedMetricSource(1,"Sales","OrderDetail","Amount"),
        published_dimensions=dimensions,
    )


def test_where_precedes_group_and_values_are_parameters():
    result=compile()
    assert result.sql=='SELECT "RegionCode" AS "dimension", SUM("Amount") AS "value" FROM "Sales"."OrderDetail" WHERE "StatusCode" IN (%s, %s, %s) GROUP BY "RegionCode" ORDER BY "value" DESC LIMIT 5'
    assert result.parameters==("O","T","TO")


def test_eq_uses_bound_value():
    result=compile(operator="EQ",values=("O",))
    assert 'WHERE "StatusCode" = %s GROUP BY' in result.sql
    assert result.parameters==("O",)


def test_injection_is_only_a_parameter():
    payload="O' OR TRUE --"
    result=compile(operator="EQ",values=(payload,))
    assert payload not in result.sql
    assert result.parameters==(payload,)


def test_missing_published_filter_dimension_rejected():
    with pytest.raises(ValueError):
        compile(filter_dimension="OrderDetail.Unknown")


def test_cross_table_filter_rejected():
    with pytest.raises(ValueError,match="source mismatch"):
        compile(filter_table="Different")


@pytest.mark.parametrize("values", [(),("O",None)])
def test_invalid_filter_values_rejected(values):
    with pytest.raises(ValueError):
        compile(values=values)


def test_unsupported_operator_rejected():
    with pytest.raises(ValueError,match="operator"):
        compile(operator="LIKE")


def test_limit_still_enforced():
    with pytest.raises(ValueError,match="positive bounded"):
        compile(limit=0)
