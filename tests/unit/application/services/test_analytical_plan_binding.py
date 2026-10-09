import pytest

from datapilot.application.services.analytical_plan import (
    AnalyticalOperation as Op, AnalyticalPlan, PlanStep,
)
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan


def _plan(metric="Revenue", dimension="Customer"):
    return AnalyticalPlan(
        sources=("orders",),
        steps=(
            PlanStep("group", Op.GROUP, ("orders",), {"dimension": dimension}),
            PlanStep("total", Op.AGGREGATE, ("group",), {"metric": metric}),
        ),
        output="total",
    )


def test_binds_approved_metric_and_dimension_case_insensitively():
    bound = bind_analytical_plan(
        _plan("revenue", "customer"),
        approved_metrics=[{"name": "Revenue"}],
        approved_dimensions=[{"name": "Customer"}],
    )
    assert [(r.kind, r.name) for r in bound.references] == [
        ("dimension", "Customer"), ("metric", "Revenue"),
    ]


@pytest.mark.parametrize("metrics,dimensions", [
    ([], [{"name": "Customer"}]),
    ([{"name": "Revenue"}], []),
    ([{"name": "Revenue"}, {"name": "revenue"}], [{"name": "Customer"}]),
])
def test_rejects_missing_or_ambiguous_governed_reference(metrics, dimensions):
    with pytest.raises(ValueError, match="Unresolved or ambiguous"):
        bind_analytical_plan(
            _plan(), approved_metrics=metrics, approved_dimensions=dimensions,
        )


def test_does_not_guess_metric_from_physical_column():
    with pytest.raises(ValueError, match="metric"):
        bind_analytical_plan(
            _plan("sales_amount"),
            approved_metrics=[{"name": "Revenue"}],
            approved_dimensions=[{"name": "Customer"}],
        )


def test_ranking_metric_and_output_metric_are_independently_bound():
    plan = AnalyticalPlan(
        sources=("fleet",),
        steps=(
            PlanStep("rank", Op.RANK, ("fleet",), {
                "metric": "Capacity", "dimension": "Operator",
            }),
            PlanStep("count", Op.AGGREGATE, ("rank",), {"metric": "Vessel Count"}),
        ),
        output="count",
    )
    bound = bind_analytical_plan(
        plan,
        approved_metrics=[{"name": "Capacity"}, {"name": "Vessel Count"}],
        approved_dimensions=[{"name": "Operator"}],
    )
    assert [r.name for r in bound.references] == ["Capacity", "Operator", "Vessel Count"]


def test_time_role_requires_governed_time_dimension():
    plan = AnalyticalPlan(
        sources=("sales",),
        steps=(PlanStep("window", Op.TIME_WINDOW, ("sales",), {"role": "Order Date"}),),
        output="window",
    )
    with pytest.raises(ValueError, match="time_dimension"):
        bind_analytical_plan(plan, approved_metrics=[], approved_dimensions=[])
    bound = bind_analytical_plan(
        plan, approved_metrics=[], approved_dimensions=[],
        approved_time_dimensions=[{"name": "Order Date"}],
    )
    assert bound.references[0].name == "Order Date"


def test_non_semantic_filter_parameters_are_not_inferred_as_metrics():
    plan = AnalyticalPlan(
        sources=("assets",),
        steps=(PlanStep("filter", Op.FILTER, ("assets",), {"status": "active"}),),
        output="filter",
    )
    bound = bind_analytical_plan(plan, approved_metrics=[], approved_dimensions=[])
    assert bound.references == ()
