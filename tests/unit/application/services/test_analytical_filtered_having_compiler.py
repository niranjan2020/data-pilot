import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan
from datapilot.application.services.analytical_sql_compiler import (
    GovernedMetricSource, compile_analytical_filtered_having_limit,
)

DIMENSIONS=(
    AnalyticalDimension("Ownership",1,"Vessel","astra","vessel","ownership_status"),
    AnalyticalDimension("Status",1,"Vessel","astra","vessel","vessel_status"),
    AnalyticalDimension("Operator",1,"Vessel","astra","vessel","operator"),
)


def build(*, threshold=50,operator="GT",threshold_metric="VesselCount",filters=None):
    if filters is None:
        filters=[
            ("Vessel.Ownership","IN",("O","T")),
            ("Vessel.Status","EQ",("DELIVERED",)),
        ]
    steps=[]
    previous="vessels"
    for index,(dimension,op,values) in enumerate(filters):
        name=f"filter{index}"
        steps.append(PlanStep(name,AnalyticalOperation.FILTER,(previous,),
                              {"dimension":dimension,"operator":op,"values":values}))
        previous=name
    steps.extend((
        PlanStep("group",AnalyticalOperation.GROUP,(previous,),{"dimension":"Vessel.Operator"}),
        PlanStep("aggregate",AnalyticalOperation.AGGREGATE,("group",),{"metric":"VesselCount"}),
        PlanStep("threshold",AnalyticalOperation.THRESHOLD,("aggregate",),
                 {"metric":threshold_metric,"operator":operator,"value":threshold}),
        PlanStep("sort",AnalyticalOperation.SORT,("threshold",),
                 {"metric":"VesselCount","direction":"DESC"}),
        PlanStep("limit",AnalyticalOperation.LIMIT,("sort",),{"count":10}),
    ))
    plan=AnalyticalPlan(sources=("vessels",),steps=tuple(steps),output="limit")
    bound=bind_analytical_plan(
        plan,approved_dimensions=[{"name":f"Vessel.{d.name}"} for d in DIMENSIONS],
        approved_metrics=[{"name":"VesselCount"},{"name":"Revenue"}],
    )
    return unify_physical_analytical_plan(
        bound,published_dimensions=DIMENSIONS,
        published_metrics=tuple(
            {"name":name,"entity_id":1,"attribute_name":"id","aggregation":"COUNT",
             "calculation_expression":None} for name in ("VesselCount","Revenue")
        ),published_time_dimensions=(),
    )


def compile(plan,**kwargs):
    return compile_analytical_filtered_having_limit(
        plan,metric_source=GovernedMetricSource(1,"astra","vessel","id"),
        published_dimensions=DIMENSIONS,**kwargs,
    )


def test_where_and_having_clause_order_and_parameters():
    result=compile(build())
    assert 'WHERE "ownership_status" IN (%s, %s) AND "vessel_status" = %s' in result.sql
    assert 'HAVING COUNT("id") > %s' in result.sql
    assert result.sql.index("WHERE") < result.sql.index("GROUP BY")
    assert result.sql.index("GROUP BY") < result.sql.index("HAVING")
    assert result.sql.index("HAVING") < result.sql.index("ORDER BY")
    assert result.parameters==("O","T","DELIVERED",50)


def test_single_filter_and_threshold():
    result=compile(build(filters=[("Vessel.Status","EQ",("DELIVERED",))]))
    assert result.parameters==("DELIVERED",50)


def test_filter_injection_remains_bound():
    payload="O' OR TRUE --"
    result=compile(build(filters=[("Vessel.Ownership","EQ",(payload,))]))
    assert payload not in result.sql
    assert result.parameters==(payload,50)


def test_filter_cap_still_enforced():
    with pytest.raises(ValueError,match="bounds"):
        compile(build(),max_filters=1)


def test_invalid_having_value_rejected():
    with pytest.raises(ValueError,match="finite numeric"):
        compile(build(threshold="50"))


def test_unsupported_having_operator_rejected():
    with pytest.raises(ValueError,match="comparison operator"):
        compile(build(operator="LIKE"))


def test_having_metric_must_match_aggregation():
    with pytest.raises(ValueError,match="existing aggregated metric"):
        compile(build(threshold_metric="Revenue"))


def test_empty_filter_chain_rejected():
    with pytest.raises(ValueError,match="Unsupported"):
        compile(build(filters=[]))


def test_cross_table_filter_rejected():
    altered=(
        AnalyticalDimension("Ownership",1,"Vessel","astra","other","ownership_status"),
        *DIMENSIONS[1:],
    )
    with pytest.raises(ValueError,match="source mismatch"):
        compile_analytical_filtered_having_limit(
            build(),metric_source=GovernedMetricSource(1,"astra","vessel","id"),
            published_dimensions=altered,
        )
