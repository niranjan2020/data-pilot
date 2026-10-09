"""Regression coverage for composer integration into existing governed paths."""

from datapilot.application.services.analytical_sql_compiler import (
    _compose_validated_grouped_limit,
    GovernedMetricSource,
)
from datapilot.application.services.analytical_sql_composition import BoundPredicate

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan


def physical():
    """Build a complete governed plan without importing another test module."""
    plan = AnalyticalPlan(
        sources=("sales",),
        steps=(
            PlanStep("group", AnalyticalOperation.GROUP, ("sales",),
                     {"dimension": "OrderDetail.Region"}),
            PlanStep("aggregate", AnalyticalOperation.AGGREGATE, ("group",),
                     {"metric": "Revenue"}),
            PlanStep("sort", AnalyticalOperation.SORT, ("aggregate",),
                     {"metric": "Revenue", "direction": "DESC"}),
            PlanStep("limit", AnalyticalOperation.LIMIT, ("sort",),
                     {"count": 5}),
        ),
        output="limit",
    )
    bound = bind_analytical_plan(
        plan,
        approved_dimensions=[{"name": "OrderDetail.Region"}],
        approved_metrics=[{"name": "Revenue"}],
    )
    return unify_physical_analytical_plan(
        bound,
        published_dimensions=(
            AnalyticalDimension(
                "Region", 1, "OrderDetail", "Sales", "OrderDetail", "RegionCode"
            ),
        ),
        published_metrics=(
            {
                "name": "Revenue",
                "entity_id": 1,
                "attribute_name": "Amount",
                "aggregation": "SUM",
                "calculation_expression": None,
            },
        ),
        published_time_dimensions=(),
    )



def test_shared_composer_matches_legacy_grouped_sql():
    plan=physical()
    source=GovernedMetricSource(1,"Sales","OrderDetail","Amount")
    result=_compose_validated_grouped_limit(plan,source)
    assert result.sql.endswith('GROUP BY "RegionCode" ORDER BY "value" DESC LIMIT 5')
    assert result.parameters==()


def test_composer_preserves_where_then_having_parameter_order():
    plan=physical()
    source=GovernedMetricSource(1,"Sales","OrderDetail","Amount")
    result=_compose_validated_grouped_limit(
        plan,source,
        where=(BoundPredicate('"StatusCode" IN (%s, %s)',("O","TO")),),
        having=(BoundPredicate('SUM("Amount") > %s',(100,)),),
    )
    assert result.sql.index("WHERE") < result.sql.index("GROUP BY")
    assert result.sql.index("GROUP BY") < result.sql.index("HAVING")
    assert result.sql.index("HAVING") < result.sql.index("ORDER BY")
    assert result.parameters==("O","TO",100)
