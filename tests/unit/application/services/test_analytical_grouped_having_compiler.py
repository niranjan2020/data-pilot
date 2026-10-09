import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan
from datapilot.application.services.analytical_sql_compiler import (
    GovernedMetricSource, compile_analytical_grouped_having,
)


def fixture(*, operator="GT", value=100000, threshold_metric="Revenue",
            sort_metric="Revenue", limit=5):
    plan=AnalyticalPlan(sources=("sales",),steps=(
        PlanStep("group",AnalyticalOperation.GROUP,("sales",),{"dimension":"OrderDetail.Region"}),
        PlanStep("aggregate",AnalyticalOperation.AGGREGATE,("group",),{"metric":"Revenue"}),
        PlanStep("threshold",AnalyticalOperation.THRESHOLD,("aggregate",),
                 {"metric":threshold_metric,"operator":operator,"value":value}),
        PlanStep("sort",AnalyticalOperation.SORT,("threshold",),
                 {"metric":sort_metric,"direction":"DESC"}),
        PlanStep("limit",AnalyticalOperation.LIMIT,("sort",),{"count":limit}),
    ),output="limit")
    bound=bind_analytical_plan(
        plan,approved_dimensions=[{"name":"OrderDetail.Region"}],
        approved_metrics=[{"name":"Revenue"},{"name":"Units"}],
    )
    return unify_physical_analytical_plan(
        bound,published_dimensions=(
            AnalyticalDimension("Region",1,"OrderDetail","Sales","OrderDetail","RegionCode"),
        ),published_metrics=tuple(
            {"name":name,"entity_id":1,"attribute_name":"Amount",
             "aggregation":"SUM","calculation_expression":None}
            for name in ("Revenue","Units")
        ),published_time_dimensions=(),
    )


def compile(**kwargs):
    return compile_analytical_grouped_having(
        fixture(**kwargs),
        metric_source=GovernedMetricSource(1,"Sales","OrderDetail","Amount"),
    )


@pytest.mark.parametrize("operator,symbol",[
    ("GT",">"),("GTE",">="),("LT","<"),("LTE","<="),("EQ","="),
])
def test_having_operator_compiles(operator,symbol):
    result=compile(operator=operator)
    assert f'HAVING SUM("Amount") {symbol} %s ORDER BY' in result.sql
    assert result.parameters==(100000,)
    assert result.sql.index("GROUP BY") < result.sql.index("HAVING") < result.sql.index("ORDER BY")


def test_having_value_never_interpolated():
    result=compile(value=987654321)
    assert "987654321" not in result.sql
    assert result.parameters==(987654321,)


@pytest.mark.parametrize("value",[True,None,"100",float("nan"),float("inf")])
def test_invalid_threshold_value_rejected(value):
    with pytest.raises(ValueError,match="finite numeric"):
        compile(value=value)


def test_invalid_operator_rejected():
    with pytest.raises(ValueError,match="comparison operator"):
        compile(operator="GT; DROP TABLE")


def test_different_metric_rejected():
    with pytest.raises(ValueError,match="existing aggregated metric"):
        compile(threshold_metric="Units")


def test_sort_validation_preserved():
    with pytest.raises(ValueError,match="existing grouped output"):
        compile(sort_metric="Units")


def test_limit_validation_preserved():
    with pytest.raises(ValueError,match="positive bounded"):
        compile(limit=0)
