"""Batch acceptance matrix: governed SQL placeholder positions and AST roles.

No live datasource or provider is needed. Fixtures are deliberately cross-domain.
"""
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


@pytest.fixture
def build():
    def factory(*, domain="sales", filters=(), threshold=None, direction="DESC",
                limit=10, aggregation="COUNT"):
        schema,table=("Sales","OrderDetail") if domain=="sales" else ("astra","vessel")
        dimensions=(
            AnalyticalDimension("Category",1,table,schema,table,"category_code"),
            AnalyticalDimension("Status",1,table,schema,table,"status_code"),
            AnalyticalDimension("Group",1,table,schema,table,"group_code"),
        )
        steps=[]
        previous="source"
        for index,(field,op,values) in enumerate(filters):
            step_id=f"filter{index}"
            steps.append(PlanStep(step_id,AnalyticalOperation.FILTER,(previous,),
                                  {"dimension":f"{table}.{field}","operator":op,"values":values}))
            previous=step_id
        steps.extend((
            PlanStep("group",AnalyticalOperation.GROUP,(previous,),{"dimension":f"{table}.Group"}),
            PlanStep("aggregate",AnalyticalOperation.AGGREGATE,("group",),{"metric":"Measure"}),
        ))
        previous="aggregate"
        if threshold is not None:
            steps.append(PlanStep("threshold",AnalyticalOperation.THRESHOLD,("aggregate",),
                                  {"metric":"Measure","operator":"GT","value":threshold}))
            previous="threshold"
        steps.extend((
            PlanStep("sort",AnalyticalOperation.SORT,(previous,),
                     {"metric":"Measure","direction":direction}),
            PlanStep("limit",AnalyticalOperation.LIMIT,("sort",),{"count":limit}),
        ))
        logical=AnalyticalPlan(sources=("source",),steps=tuple(steps),output="limit")
        bound=bind_analytical_plan(
            logical,
            approved_dimensions=[{"name":f"{table}.{d.name}"} for d in dimensions],
            approved_metrics=[{"name":"Measure"}],
        )
        physical=unify_physical_analytical_plan(
            bound,published_dimensions=dimensions,
            published_metrics=({"name":"Measure","entity_id":1,"attribute_name":"id",
                                "aggregation":aggregation,"calculation_expression":None},),
            published_time_dimensions=(),
        )
        source=GovernedMetricSource(1,schema,table,"id")
        return physical,source,dimensions
    return factory


def checked(build,**kwargs):
    physical,source,dimensions=build(**kwargs)
    compiled=compile_governed_analytical_plan(
        physical,metric_source=source,published_dimensions=dimensions,
    )
    result=verify_governed_analytical_sql(
        physical,compiled,metric_source=source,published_dimensions=dimensions,
    )
    assert result.verified, result.reason
    return physical,source,dimensions,compiled


@pytest.mark.parametrize("domain",["sales","vessel"])
@pytest.mark.parametrize("filters,threshold",[
    ((),None),
    ((("Category","EQ",("O",)),),None),
    ((("Category","IN",("O","TO")),),None),
    ((("Category","EQ",("O",)),),25),
    ((("Category","IN",("O","TO")),("Status","EQ",("ACTIVE",))),None),
    ((("Category","IN",("O","TO")),("Status","EQ",("ACTIVE",))),25),
    ((("Status","EQ",("ACTIVE",)),("Category","IN",("O","TO"))),25),
])
def test_supported_query_matrix(build,domain,filters,threshold):
    checked(build,domain=domain,filters=filters,threshold=threshold)


@pytest.mark.parametrize("payload",[
    "O' OR 1=1 --",
    "a;b",
    "unicode Ω 東京",
    "value %s",
    "",
])
def test_untrusted_filter_value_remains_bound(build,payload):
    _,_,_,compiled=checked(build,filters=(("Category","EQ",(payload,)),),threshold=5)
    assert compiled.parameters==(payload,5)
    assert payload not in compiled.sql


@pytest.mark.parametrize("direction,limit,aggregation",[
    ("ASC",1,"COUNT"),
    ("DESC",100,"SUM"),
    ("ASC",999,"AVG"),
    ("DESC",10,"MAX"),
    ("ASC",10,"MIN"),
])
def test_supported_sort_limit_and_aggregations(build,direction,limit,aggregation):
    checked(build,direction=direction,limit=limit,aggregation=aggregation)


@pytest.mark.parametrize("tamper",[
    lambda q: replace(q,sql=q.sql.replace(' GROUP BY ',' GROUP BY "status_code", ',1)),
    lambda q: replace(q,sql=q.sql.replace(' ORDER BY ',' ORDER BY "dimension" ASC, ',1)),
    lambda q: replace(q,sql=q.sql.replace(' LIMIT 10',' LIMIT 100',1)),
    lambda q: replace(q,sql=q.sql.replace(' COUNT(',' SUM(',1)),
    lambda q: replace(q,sql=q.sql.replace(' WHERE ',' WHERE TRUE AND ',1)),
    lambda q: replace(q,sql=q.sql+'; SELECT 1'),
    lambda q: replace(q,parameters=tuple(reversed(q.parameters))),
    lambda q: replace(q,parameters=q.parameters[:-1]),
    lambda q: replace(q,dialect="mysql"),
])
def test_adversarial_compiled_sql_rejected(build,tamper):
    physical,source,dimensions,compiled=checked(
        build,filters=(("Category","IN",("O","TO")),("Status","EQ",("ACTIVE",))),
        threshold=25,
    )
    modified=tamper(compiled)
    assert modified != compiled
    result=verify_governed_analytical_sql(
        physical,modified,metric_source=source,published_dimensions=dimensions,
    )
    assert not result.verified


@pytest.mark.parametrize("max_rows,max_filters",[(9,10),(1000,1),(0,10)])
def test_governance_bounds_fail_closed(build,max_rows,max_filters):
    physical,source,dimensions,compiled=checked(
        build,filters=(("Category","EQ",("O",)),("Status","EQ",("ACTIVE",))),
    )
    result=verify_governed_analytical_sql(
        physical,compiled,metric_source=source,published_dimensions=dimensions,
        max_rows=max_rows,max_filters=max_filters,
    )
    assert not result.verified
