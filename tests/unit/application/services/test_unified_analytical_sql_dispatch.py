"""Contract tests for unified governed analytical compiler dispatch."""
from dataclasses import replace

import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan
from datapilot.application.services.analytical_sql_compiler import (
    GovernedMetricSource, compile_governed_analytical_plan,
)

DIMENSIONS=(
    AnalyticalDimension("Status",1,"Vessel","astra","vessel","vessel_status"),
    AnalyticalDimension("Ownership",1,"Vessel","astra","vessel","ownership_status"),
    AnalyticalDimension("Operator",1,"Vessel","astra","vessel","operator"),
)
SOURCE=GovernedMetricSource(1,"astra","vessel","id")


def build(*, filters=(), having=None, sort_direction="DESC"):
    steps=[]
    previous="vessels"
    for index,(dimension,operator,values) in enumerate(filters):
        name=f"filter{index}"
        steps.append(PlanStep(name,AnalyticalOperation.FILTER,(previous,),
                              {"dimension":dimension,"operator":operator,"values":values}))
        previous=name
    steps.extend((
        PlanStep("group",AnalyticalOperation.GROUP,(previous,),{"dimension":"Vessel.Operator"}),
        PlanStep("aggregate",AnalyticalOperation.AGGREGATE,("group",),{"metric":"VesselCount"}),
    ))
    previous="aggregate"
    if having is not None:
        steps.append(PlanStep("threshold",AnalyticalOperation.THRESHOLD,("aggregate",),
                              {"metric":"VesselCount","operator":"GT","value":having}))
        previous="threshold"
    steps.extend((
        PlanStep("sort",AnalyticalOperation.SORT,(previous,),
                 {"metric":"VesselCount","direction":sort_direction}),
        PlanStep("limit",AnalyticalOperation.LIMIT,("sort",),{"count":10}),
    ))
    plan=AnalyticalPlan(sources=("vessels",),steps=tuple(steps),output="limit")
    bound=bind_analytical_plan(
        plan,approved_dimensions=[{"name":f"Vessel.{d.name}"} for d in DIMENSIONS],
        approved_metrics=[{"name":"VesselCount"}],
    )
    return unify_physical_analytical_plan(
        bound,published_dimensions=DIMENSIONS,
        published_metrics=({"name":"VesselCount","entity_id":1,"attribute_name":"id",
                            "aggregation":"COUNT","calculation_expression":None},),
        published_time_dimensions=(),
    )


def compile(plan,**kwargs):
    return compile_governed_analytical_plan(
        plan,metric_source=SOURCE,published_dimensions=DIMENSIONS,**kwargs,
    )


def test_dispatch_basic_grouped_limit():
    result=compile(build())
    assert result.sql.endswith('GROUP BY "operator" ORDER BY "value" DESC LIMIT 10')
    assert result.parameters==()


def test_dispatch_grouped_having():
    result=compile(build(having=50))
    assert 'HAVING COUNT("id") > %s' in result.sql
    assert result.parameters==(50,)


def test_dispatch_single_filter():
    result=compile(build(filters=(("Vessel.Status","EQ",("DELIVERED",)),)))
    assert 'WHERE "vessel_status" = %s' in result.sql
    assert result.parameters==("DELIVERED",)


def test_dispatch_multiple_filters():
    result=compile(build(filters=(
        ("Vessel.Status","EQ",("DELIVERED",)),
        ("Vessel.Ownership","IN",("O","TO")),
    )))
    assert result.parameters==("DELIVERED","O","TO")


def test_dispatch_filters_and_having():
    result=compile(build(filters=(("Vessel.Status","EQ",("DELIVERED",)),),having=50))
    assert result.parameters==("DELIVERED",50)
    assert result.sql.index("WHERE") < result.sql.index("HAVING")


def test_filter_cap_enforced():
    with pytest.raises(ValueError,match="filter count"):
        compile(build(filters=(("Vessel.Status","EQ",("DELIVERED",)),)),max_filters=0)


def test_invalid_sort_rejected_by_delegated_compiler():
    with pytest.raises(ValueError,match="direction"):
        compile(build(sort_direction="DROP"))


def test_invalid_having_rejected_by_delegated_compiler():
    with pytest.raises(ValueError,match="finite numeric"):
        compile(build(having="50"))


def test_unsupported_operation_rejected():
    original=build()
    plan=original.bound_plan.plan
    steps=plan.steps
    modified=replace(plan,steps=steps[:-1]+(
        replace(steps[-1],operation=AnalyticalOperation.RANK),))
    bad=replace(original,bound_plan=replace(original.bound_plan,plan=modified))
    with pytest.raises(ValueError,match="Unsupported"):
        compile(bad)
