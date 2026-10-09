import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan
from datapilot.application.services.analytical_sql_compiler import (
    GovernedMetricSource, compile_analytical_multi_filtered_grouped_limit,
)


DIMENSIONS=(
    AnalyticalDimension("Ownership",1,"Vessel","astra","vessel","ownership_status"),
    AnalyticalDimension("Status",1,"Vessel","astra","vessel","vessel_status"),
    AnalyticalDimension("Segment",1,"Vessel","astra","vessel","segment"),
    AnalyticalDimension("Operator",1,"Vessel","astra","vessel","operator"),
)


def physical(*, filters=None):
    if filters is None:
        filters=[
            ("Vessel.Ownership","IN",("O","TO")),
            ("Vessel.Status","EQ",("DELIVERED",)),
            ("Vessel.Segment","EQ",("Container",)),
        ]
    steps=[]
    previous="vessels"
    for index,(name,operator,values) in enumerate(filters):
        step_id=f"filter{index}"
        steps.append(PlanStep(step_id,AnalyticalOperation.FILTER,(previous,),
                              {"dimension":name,"operator":operator,"values":values}))
        previous=step_id
    steps.extend((
        PlanStep("group",AnalyticalOperation.GROUP,(previous,),{"dimension":"Vessel.Operator"}),
        PlanStep("aggregate",AnalyticalOperation.AGGREGATE,("group",),{"metric":"VesselCount"}),
        PlanStep("sort",AnalyticalOperation.SORT,("aggregate",),
                 {"metric":"VesselCount","direction":"DESC"}),
        PlanStep("limit",AnalyticalOperation.LIMIT,("sort",),{"count":10}),
    ))
    plan=AnalyticalPlan(sources=("vessels",),steps=tuple(steps),output="limit")
    bound=bind_analytical_plan(
        plan,approved_dimensions=[{"name":f"Vessel.{d.name}"} for d in DIMENSIONS],
        approved_metrics=[{"name":"VesselCount"}],
    )
    return unify_physical_analytical_plan(
        bound,published_dimensions=DIMENSIONS,
        published_metrics=({"name":"VesselCount","entity_id":1,
                            "attribute_name":"id","aggregation":"COUNT",
                            "calculation_expression":None},),
        published_time_dimensions=(),
    )


def compile(plan, **kwargs):
    return compile_analytical_multi_filtered_grouped_limit(
        plan,metric_source=GovernedMetricSource(1,"astra","vessel","id"),
        published_dimensions=DIMENSIONS,**kwargs,
    )


def test_three_governed_filters_compose_in_order():
    result=compile(physical())
    assert 'WHERE ("ownership_status" IN (%s, %s)) AND ("vessel_status" = %s) AND ("segment" = %s)' not in result.sql
    assert 'WHERE "ownership_status" IN (%s, %s) AND "vessel_status" = %s AND "segment" = %s' in result.sql
    assert result.sql.index("WHERE") < result.sql.index("GROUP BY")
    assert result.parameters==("O","TO","DELIVERED","Container")
    assert result.sql.endswith('ORDER BY "value" DESC LIMIT 10')


def test_single_filter_supported():
    result=compile(physical(filters=[("Vessel.Status","EQ",("DELIVERED",))]))
    assert result.parameters==("DELIVERED",)


def test_filter_values_never_interpolated():
    payload="O' OR TRUE --"
    result=compile(physical(filters=[("Vessel.Ownership","EQ",(payload,))]))
    assert payload not in result.sql
    assert result.parameters==(payload,)


def test_filter_count_bounded():
    with pytest.raises(ValueError,match="bounds"):
        compile(physical(),max_filters=2)


def test_invalid_filter_cap_rejected():
    with pytest.raises(ValueError,match="maximum"):
        compile(physical(),max_filters=True)


def test_unpublished_filter_dimension_rejected():
    with pytest.raises(ValueError):
        physical(filters=[("Vessel.Unknown","EQ",("X",))])


def test_invalid_filter_operator_rejected():
    with pytest.raises(ValueError,match="operator"):
        compile(physical(filters=[("Vessel.Status","LIKE",("DELIVERED",))]))


def test_empty_values_rejected():
    with pytest.raises(ValueError):
        compile(physical(filters=[("Vessel.Status","IN",())]))


def test_limit_still_validated():
    plan=physical()
    from dataclasses import replace
    from datapilot.application.services.analytical_plan_binding import BoundAnalyticalPlan
    modified=replace(plan.bound_plan.plan,steps=plan.bound_plan.plan.steps[:-1]+(
        replace(plan.bound_plan.plan.steps[-1],parameters={"count":0}),))
    bad=replace(plan,bound_plan=replace(plan.bound_plan,plan=modified))
    with pytest.raises(ValueError,match="positive bounded"):
        compile(bad)
