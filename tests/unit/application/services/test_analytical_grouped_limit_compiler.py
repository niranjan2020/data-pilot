import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan
from datapilot.application.services.analytical_sql_compiler import (
    GovernedMetricSource, compile_analytical_grouped_limit,
)


def physical(*, count=5, direction="DESC", target="metric", limit_params=None,
             limit_operation=AnalyticalOperation.LIMIT, sort_operation=AnalyticalOperation.SORT):
    sort_target={"metric":"Revenue"} if target=="metric" else {"dimension":"OrderDetail.Region"}
    plan=AnalyticalPlan(sources=("sales",),steps=(
        PlanStep("group",AnalyticalOperation.GROUP,("sales",),{"dimension":"OrderDetail.Region"}),
        PlanStep("aggregate",AnalyticalOperation.AGGREGATE,("group",),{"metric":"Revenue"}),
        PlanStep("sort",sort_operation,("aggregate",),{**sort_target,"direction":direction}),
        PlanStep("limit",limit_operation,("sort",),{"count":count} if limit_params is None else limit_params),
    ),output="limit")
    bound=bind_analytical_plan(plan,approved_dimensions=[{"name":"OrderDetail.Region"}],
        approved_metrics=[{"name":"Revenue"}])
    return unify_physical_analytical_plan(
        bound,
        published_dimensions=(AnalyticalDimension(
            "Region",1,"OrderDetail","Sales","OrderDetail","RegionCode",
        ),),
        published_metrics=({"name":"Revenue","entity_id":1,"attribute_name":"Amount",
            "aggregation":"SUM","calculation_expression":None},),
        published_time_dimensions=(),
    )


def compile(plan, *, max_rows=1000):
    return compile_analytical_grouped_limit(
        plan,
        metric_source=GovernedMetricSource(1,"Sales","OrderDetail","Amount"),
        max_rows=max_rows,
    ).sql


@pytest.mark.parametrize("count", [1,5,1000])
def test_bounded_limit_compiles(count):
    sql=compile(physical(count=count))
    assert sql.endswith(f'ORDER BY "value" DESC LIMIT {count}')
    assert 'GROUP BY "RegionCode"' in sql


def test_dimension_sort_with_limit():
    assert compile(physical(target="dimension",direction="ASC")).endswith(
        'ORDER BY "dimension" ASC LIMIT 5'
    )


@pytest.mark.parametrize("count", [0,-1,1001,True,1.5,"5",None])
def test_invalid_limit_rejected(count):
    with pytest.raises(ValueError,match="positive bounded integer"):
        compile(physical(count=count))


def test_custom_cap_rejects_excessive_count():
    with pytest.raises(ValueError,match="positive bounded integer"):
        compile(physical(count=11),max_rows=10)


def test_invalid_cap_rejected():
    with pytest.raises(ValueError,match="maximum row count"):
        compile(physical(),max_rows=True)


def test_extra_limit_parameters_rejected():
    with pytest.raises(ValueError,match="exactly one"):
        compile(physical(limit_params={"count":5,"offset":1}))


def test_missing_count_rejected():
    with pytest.raises(ValueError,match="exactly one"):
        compile(physical(limit_params={}))


def test_wrong_final_operation_rejected():
    with pytest.raises(ValueError,match="Unsupported"):
        compile(physical(limit_operation=AnalyticalOperation.PROJECT))


def test_sort_validation_is_preserved():
    with pytest.raises(ValueError,match="direction"):
        compile(physical(direction="DROP"))


def test_unordered_limit_is_rejected():
    with pytest.raises(ValueError,match="Unsupported"):
        compile(physical(sort_operation=AnalyticalOperation.PROJECT))
