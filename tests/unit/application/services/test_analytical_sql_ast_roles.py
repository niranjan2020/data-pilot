"""Cross-domain independent AST role checks for governed analytical queries."""
from dataclasses import replace

import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan
from datapilot.application.services.analytical_sql_compiler import (
    GovernedMetricSource, compile_governed_analytical_plan,
)
from datapilot.application.services.analytical_sql_verification import verify_governed_analytical_sql


@pytest.mark.parametrize("schema,table,dimension,column,metric_column",[
    ("Sales","OrderDetail","Region","RegionCode","Amount"),
    ("astra","vessel","Operator","operator","id"),
])
def test_independent_ast_roles_across_domains(schema,table,dimension,column,metric_column):
    source=GovernedMetricSource(1,schema,table,metric_column)
    semantic=f"{table}.{dimension}"
    physical_dimension=AnalyticalDimension(dimension,1,table,schema,table,column)
    plan=AnalyticalPlan(sources=("source",),steps=(
        PlanStep("group",AnalyticalOperation.GROUP,("source",),{"dimension":semantic}),
        PlanStep("aggregate",AnalyticalOperation.AGGREGATE,("group",),{"metric":"Measure"}),
        PlanStep("sort",AnalyticalOperation.SORT,("aggregate",),{"metric":"Measure","direction":"DESC"}),
        PlanStep("limit",AnalyticalOperation.LIMIT,("sort",),{"count":5}),
    ),output="limit")
    bound=bind_analytical_plan(plan,approved_dimensions=[{"name":semantic}],
                              approved_metrics=[{"name":"Measure"}])
    physical=unify_physical_analytical_plan(
        bound,published_dimensions=(physical_dimension,),
        published_metrics=({"name":"Measure","entity_id":1,"attribute_name":metric_column,
                            "aggregation":"SUM","calculation_expression":None},),
        published_time_dimensions=(),
    )
    compiled=compile_governed_analytical_plan(physical,metric_source=source)
    verified=verify_governed_analytical_sql(physical,compiled,metric_source=source)
    assert verified.verified, verified.reason


def test_ast_rejects_compiler_authorized_query_with_inconsistent_physical_metric():
    """Changing governed physical mapping without recompiling cannot be accepted."""
    schema,table="Sales","OrderDetail"
    dimension=AnalyticalDimension("Region",1,table,schema,table,"RegionCode")
    plan=AnalyticalPlan(sources=("source",),steps=(
        PlanStep("group",AnalyticalOperation.GROUP,("source",),{"dimension":"OrderDetail.Region"}),
        PlanStep("aggregate",AnalyticalOperation.AGGREGATE,("group",),{"metric":"Revenue"}),
        PlanStep("sort",AnalyticalOperation.SORT,("aggregate",),{"metric":"Revenue","direction":"DESC"}),
        PlanStep("limit",AnalyticalOperation.LIMIT,("sort",),{"count":5}),
    ),output="limit")
    bound=bind_analytical_plan(plan,approved_dimensions=[{"name":"OrderDetail.Region"}],
                              approved_metrics=[{"name":"Revenue"}])
    physical=unify_physical_analytical_plan(
        bound,published_dimensions=(dimension,),
        published_metrics=({"name":"Revenue","entity_id":1,"attribute_name":"Amount",
                            "aggregation":"SUM","calculation_expression":None},),
        published_time_dimensions=(),
    )
    source=GovernedMetricSource(1,schema,table,"Amount")
    compiled=compile_governed_analytical_plan(physical,metric_source=source)
    assert verify_governed_analytical_sql(physical,compiled,metric_source=source).verified
    changed=replace(physical,metrics=tuple(
        replace(binding,aggregation="COUNT") if binding.step_id == "aggregate" else binding
        for binding in physical.metrics
    ))
    assert not verify_governed_analytical_sql(changed,compiled,metric_source=source).verified
