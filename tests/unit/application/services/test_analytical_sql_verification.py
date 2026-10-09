"""Tests for deterministic plan-to-SQL verification contract."""
from dataclasses import replace

import pytest

from datapilot.application.services.analytical_sql_compiler import (
    GovernedMetricSource, compile_governed_analytical_plan,
)
from datapilot.application.services.analytical_sql_verification import (
    verify_governed_analytical_sql,
)
from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan


DIMENSIONS=(
    AnalyticalDimension("Status",1,"Vessel","astra","vessel","vessel_status"),
    AnalyticalDimension("Operator",1,"Vessel","astra","vessel","operator"),
)
SOURCE=GovernedMetricSource(1,"astra","vessel","id")


def plan(*, filtered=True, threshold=True):
    steps=[]
    previous="vessels"
    if filtered:
        steps.append(PlanStep("filter",AnalyticalOperation.FILTER,("vessels",),
                              {"dimension":"Vessel.Status","operator":"EQ",
                               "values":("DELIVERED",)}))
        previous="filter"
    steps.extend((
        PlanStep("group",AnalyticalOperation.GROUP,(previous,),{"dimension":"Vessel.Operator"}),
        PlanStep("aggregate",AnalyticalOperation.AGGREGATE,("group",),{"metric":"VesselCount"}),
    ))
    previous="aggregate"
    if threshold:
        steps.append(PlanStep("threshold",AnalyticalOperation.THRESHOLD,("aggregate",),
                              {"metric":"VesselCount","operator":"GT","value":50}))
        previous="threshold"
    steps.extend((
        PlanStep("sort",AnalyticalOperation.SORT,(previous,),
                 {"metric":"VesselCount","direction":"DESC"}),
        PlanStep("limit",AnalyticalOperation.LIMIT,("sort",),{"count":10}),
    ))
    logical=AnalyticalPlan(sources=("vessels",),steps=tuple(steps),output="limit")
    bound=bind_analytical_plan(
        logical,approved_dimensions=[{"name":"Vessel.Status"},{"name":"Vessel.Operator"}],
        approved_metrics=[{"name":"VesselCount"}],
    )
    return unify_physical_analytical_plan(
        bound,published_dimensions=DIMENSIONS,
        published_metrics=({"name":"VesselCount","entity_id":1,"attribute_name":"id",
                            "aggregation":"COUNT","calculation_expression":None},),
        published_time_dimensions=(),
    )


def compile(p):
    return compile_governed_analytical_plan(
        p,metric_source=SOURCE,published_dimensions=DIMENSIONS,
    )


def verify(p,result):
    return verify_governed_analytical_sql(
        p,result,metric_source=SOURCE,published_dimensions=DIMENSIONS,
    )


@pytest.mark.parametrize("filtered,threshold",[
    (False,False),(False,True),(True,False),(True,True),
])
def test_supported_compiled_plan_verified(filtered,threshold):
    p=plan(filtered=filtered,threshold=threshold)
    assert verify(p,compile(p)).verified


@pytest.mark.parametrize("fragment",[
    ' LIMIT 10',' WHERE ', ' GROUP BY ', ' HAVING ', ' ORDER BY ',
])
def test_modified_sql_rejected(fragment):
    p=plan()
    original=compile(p)
    assert fragment in original.sql
    assert not verify(p,replace(original,sql=original.sql.replace(fragment," ",1))).verified


def test_altered_table_rejected():
    p=plan()
    original=compile(p)
    assert not verify(p,replace(original,sql=original.sql.replace('"vessel"','"other"'))).verified


def test_altered_parameter_rejected():
    p=plan()
    original=compile(p)
    assert not verify(p,replace(original,parameters=("ACTIVE",50))).verified


def test_missing_parameter_rejected():
    p=plan()
    original=compile(p)
    assert not verify(p,replace(original,parameters=("DELIVERED",))).verified


def test_wrong_dialect_rejected():
    p=plan()
    original=compile(p)
    assert not verify(p,replace(original,dialect="mysql")).verified


def test_invalid_compiled_contract_rejected():
    assert not verify(plan(),object()).verified


def test_governed_plan_limit_enforced():
    p=plan()
    assert not verify_governed_analytical_sql(
        p,compile(p),metric_source=SOURCE,published_dimensions=DIMENSIONS,max_rows=5,
    ).verified
