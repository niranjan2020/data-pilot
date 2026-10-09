import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan
from datapilot.application.services.analytical_sql_compiler import (
    GovernedMetricSource, compile_analytical_grouped_sort,
)


def fixture(*, kind="metric", direction="DESC", sort_name=None,
            sort_parameters=None, dimension_entity=1, metric_entity=1):
    target=sort_name or ("Revenue" if kind=="metric" else "OrderDetail.Region")
    params={kind:target,"direction":direction} if sort_parameters is None else sort_parameters
    plan=AnalyticalPlan(sources=("sales",),steps=(
        PlanStep("group",AnalyticalOperation.GROUP,("sales",),{"dimension":"OrderDetail.Region"}),
        PlanStep("aggregate",AnalyticalOperation.AGGREGATE,("group",),{"metric":"Revenue"}),
        PlanStep("sort",AnalyticalOperation.SORT,("aggregate",),params),
    ),output="sort")
    bound=bind_analytical_plan(plan,approved_dimensions=[
        {"name":"OrderDetail.Region"},{"name":"OrderDetail.Category"}
    ],approved_metrics=[{"name":"Revenue"},{"name":"Units"}])
    dimensions=(
        AnalyticalDimension("Region",dimension_entity,"OrderDetail","Sales","OrderDetail","RegionCode"),
        AnalyticalDimension("Category",dimension_entity,"OrderDetail","Sales","OrderDetail","CategoryCode"),
    )
    metrics=tuple({"name":name,"entity_id":metric_entity,"attribute_name":"Amount",
                   "aggregation":"SUM","calculation_expression":None} for name in ("Revenue","Units"))
    return unify_physical_analytical_plan(bound,published_dimensions=dimensions,
        published_metrics=metrics,published_time_dimensions=())


def compile(plan):
    return compile_analytical_grouped_sort(plan,metric_source=GovernedMetricSource(
        entity_id=1,schema_name="Sales",table_name="OrderDetail",column_name="Amount",
    )).sql


@pytest.mark.parametrize("kind,direction,alias",[
    ("metric","ASC","value"),("metric","DESC","value"),
    ("dimension","ASC","dimension"),("dimension","DESC","dimension"),
])
def test_grouped_sort_by_governed_output(kind,direction,alias):
    sql=compile(fixture(kind=kind,direction=direction))
    assert sql.endswith(f'ORDER BY "{alias}" {direction}')
    assert 'GROUP BY "RegionCode"' in sql


@pytest.mark.parametrize("direction",["desc","DOWN","DESC; DROP TABLE x",""])
def test_invalid_direction_rejected(direction):
    with pytest.raises(ValueError,match="direction"):
        compile(fixture(direction=direction))


def test_sorting_by_other_metric_is_rejected():
    with pytest.raises(ValueError,match="existing grouped output"):
        compile(fixture(sort_name="Units"))


def test_sorting_by_other_dimension_is_rejected():
    with pytest.raises(ValueError,match="existing grouped output"):
        compile(fixture(kind="dimension",sort_name="OrderDetail.Category"))


def test_cross_entity_sort_still_rejected():
    with pytest.raises(ValueError,match="Cross-entity"):
        compile(fixture(dimension_entity=2))


def test_extra_sort_parameter_rejected():
    with pytest.raises(ValueError,match="Sort requires"):
        compile(fixture(sort_parameters={"metric":"Revenue","direction":"DESC","limit":5}))


def test_missing_direction_rejected():
    with pytest.raises(ValueError,match="Sort requires"):
        compile(fixture(sort_parameters={"metric":"Revenue"}))
