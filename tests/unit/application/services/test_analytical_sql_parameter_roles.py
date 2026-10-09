"""Independent plan parameter-order verification across multiple domains."""
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


@pytest.mark.parametrize("schema,table,field,values,threshold",[
    ("Sales","OrderDetail","RegionCode",("North","West"),100),
    ("astra","vessel","ownership_status",("O","TO"),50),
])
def test_parameter_order_matches_governed_plan(schema,table,field,values,threshold):
    name=f"{table}.Category"
    dimensions=(
        AnalyticalDimension("Category",1,table,schema,table,field),
        AnalyticalDimension("Group",1,table,schema,table,"group_key"),
    )
    steps=(
        PlanStep("filter",AnalyticalOperation.FILTER,("source",),
                 {"dimension":name,"operator":"IN","values":values}),
        PlanStep("group",AnalyticalOperation.GROUP,("filter"),
                 {"dimension":f"{table}.Group"}),
        PlanStep("aggregate",AnalyticalOperation.AGGREGATE,("group"),{"metric":"Total"}),
        PlanStep("threshold",AnalyticalOperation.THRESHOLD,("aggregate"),
                 {"metric":"Total","operator":"GT","value":threshold}),
        PlanStep("sort",AnalyticalOperation.SORT,("threshold"),
                 {"metric":"Total","direction":"DESC"}),
        PlanStep("limit",AnalyticalOperation.LIMIT,("sort"),{"count":10}),
    )
    plan=AnalyticalPlan(sources=("source",),steps=steps,output="limit")
    bound=bind_analytical_plan(
        plan,approved_dimensions=[{"name":name},{"name":f"{table}.Group"}],
        approved_metrics=[{"name":"Total"}],
    )
    physical=unify_physical_analytical_plan(
        bound,published_dimensions=dimensions,
        published_metrics=({"name":"Total","entity_id":1,"attribute_name":"id",
                            "aggregation":"COUNT","calculation_expression":None},),
        published_time_dimensions=(),
    )
    source=GovernedMetricSource(1,schema,table,"id")
    compiled=compile_governed_analytical_plan(
        physical,metric_source=source,published_dimensions=dimensions,
    )
    def verify(candidate):
        return verify_governed_analytical_sql(
            physical,candidate,metric_source=source,published_dimensions=dimensions,
        )
    result=verify(compiled)
    assert result.verified, result.reason
    assert compiled.parameters == (*values,threshold)
    swapped=replace(compiled,parameters=(values[1],values[0],threshold))
    assert not verify(swapped).verified
    altered=replace(compiled,parameters=(*values,threshold+1))
    assert not verify(altered).verified
    truncated=replace(compiled,parameters=values)
    assert not verify(truncated).verified
