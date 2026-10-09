import pytest
from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import UnifiedPhysicalAnalyticalPlan, unify_physical_analytical_plan

def fixture():
    plan = AnalyticalPlan(sources=("sales",), steps=(
        PlanStep("g", AnalyticalOperation.GROUP, ("sales",), {"dimension":"Customer.Region"}),
        PlanStep("a", AnalyticalOperation.AGGREGATE, ("g",), {"metric":"Revenue"}),
        PlanStep("t", AnalyticalOperation.TIME_WINDOW, ("a",), {"role":"Order Date"}),
    ), output="t")
    bound = bind_analytical_plan(plan, approved_dimensions=[{"name":"Customer.Region"}],
        approved_metrics=[{"name":"Revenue"}], approved_time_dimensions=[{"name":"Order Date"}])
    return bound, (AnalyticalDimension("Region",1,"Customer","Sales","Customer","RegionCode"),), (
        {"name":"Revenue","entity_id":1,"attribute_name":"Amount","aggregation":"SUM","calculation_expression":None},
    ), ({"name":"Order Date","entity_id":1,"column_name":"OrderDate","role":"order_date","grain":"day"},)

def test_complete_bindings():
    b,d,m,t=fixture()
    result=unify_physical_analytical_plan(b,published_dimensions=d,published_metrics=m,published_time_dimensions=t)
    assert (len(result.dimensions),len(result.metrics),len(result.time_dimensions))==(1,1,1)
    assert result.dimensions[0].column_name=="RegionCode"
    assert result.metrics[0].attribute_name=="Amount"
    assert result.time_dimensions[0].column_name=="OrderDate"

@pytest.mark.parametrize("missing,match", [("dimension","Unknown"),("metric","Missing approved metric"),("time","Missing approved time_dimension")])
def test_missing_mapping_rejected(missing,match):
    b,d,m,t=fixture()
    if missing=="dimension": d=()
    if missing=="metric": m=()
    if missing=="time": t=()
    with pytest.raises(ValueError,match=match):
        unify_physical_analytical_plan(b,published_dimensions=d,published_metrics=m,published_time_dimensions=t)

@pytest.mark.parametrize("duplicate", [False,True])
def test_completeness_enforced(duplicate):
    b,d,m,t=fixture()
    result=unify_physical_analytical_plan(b,published_dimensions=d,published_metrics=m,published_time_dimensions=t)
    dimensions=result.dimensions+result.dimensions if duplicate else ()
    with pytest.raises(ValueError,match="Incomplete or duplicate"):
        UnifiedPhysicalAnalyticalPlan(bound_plan=b,dimensions=dimensions,metrics=result.metrics,time_dimensions=result.time_dimensions)
