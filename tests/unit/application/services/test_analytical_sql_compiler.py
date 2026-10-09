import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan
from datapilot.application.services.analytical_sql_compiler import compile_analytical_projection


def physical(*, operation=AnalyticalOperation.PROJECT, parameters=None,
             schema="Sales", table="Customer", column="RegionCode"):
    if parameters is None:
        parameters={"dimension":"Customer.Region"}
    plan=AnalyticalPlan(sources=("sales",),steps=(
        PlanStep("project",operation,("sales",),parameters),
    ),output="project")
    bound=bind_analytical_plan(plan,approved_dimensions=[{"name":"Customer.Region"}],
        approved_metrics=[],approved_time_dimensions=[])
    dimension=AnalyticalDimension("Region",1,"Customer",schema,table,column)
    return unify_physical_analytical_plan(bound,published_dimensions=(dimension,),
        published_metrics=(),published_time_dimensions=())


def test_compiles_approved_single_dimension_projection():
    result=compile_analytical_projection(physical())
    assert result.sql=='SELECT "RegionCode" FROM "Sales"."Customer"'
    assert result.dialect=="postgres"


def test_quoted_identifiers_are_escaped():
    result=compile_analytical_projection(physical(table='Order"Details',column='Odd"Column'))
    assert result.sql=='SELECT "Odd""Column" FROM "Sales"."Order""Details"'


def test_rejects_unsupported_aggregate():
    with pytest.raises(ValueError,match="Unsupported"):
        compile_analytical_projection(physical(operation=AnalyticalOperation.AGGREGATE))


def test_rejects_unknown_projection_parameters():
    with pytest.raises(ValueError,match="only one"):
        compile_analytical_projection(physical(parameters={"dimension":"Customer.Region","limit":10}))


def test_rejects_missing_governed_dimension():
    with pytest.raises(ValueError,match="requires only"):
        compile_analytical_projection(physical(parameters={}))


def test_rejects_nul_identifier():
    with pytest.raises(ValueError,match="Incomplete"):
        compile_analytical_projection(physical(column="Region\x00Code"))


def test_rejects_non_physical_plan():
    with pytest.raises(ValueError,match="Unified"):
        compile_analytical_projection(None)
