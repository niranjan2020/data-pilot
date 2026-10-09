import pytest

from datapilot.application.services.analytical_plan import (
    AnalyticalOperation as Op,
    AnalyticalPlan,
    PlanStep,
)


def test_cross_domain_filter_group_aggregate_plan():
    plan = AnalyticalPlan(
        sources=("orders",),
        steps=(
            PlanStep("filtered", Op.FILTER, ("orders",), {"status": "completed"}),
            PlanStep("grouped", Op.GROUP, ("filtered",), {"dimension": "customer"}),
            PlanStep("revenue", Op.AGGREGATE, ("grouped",), {"metric": "Revenue"}),
        ),
        output="revenue",
    )
    assert plan.operations == (Op.FILTER, Op.GROUP, Op.AGGREGATE)


def test_two_stage_cohort_plan_preserves_ranking_and_output_aggregation():
    plan = AnalyticalPlan(
        sources=("fleet",),
        steps=(
            PlanStep("capacity", Op.AGGREGATE, ("fleet",), {"metric": "Capacity"}),
            PlanStep("cohort", Op.RANK, ("capacity",), {"n": 10, "dimension": "operator"}),
            PlanStep("eligible", Op.FILTER, ("fleet",), {"status": "ON ORDER"}),
            PlanStep("cohort_rows", Op.JOIN, ("eligible", "cohort")),
            PlanStep("counts", Op.AGGREGATE, ("cohort_rows",), {"metric": "Vessel Count"}),
        ),
        output="counts",
    )
    assert plan.output == "counts"
    assert plan.steps[1].inputs == ("capacity",)


def test_comparison_and_contribution_are_generic_operations():
    plan = AnalyticalPlan(
        sources=("sales",),
        steps=(
            PlanStep("period", Op.TIME_WINDOW, ("sales",), {"role": "order_date"}),
            PlanStep("compare", Op.COMPARE, ("period",), {"metric": "Revenue"}),
            PlanStep("share", Op.CONTRIBUTION, ("compare",), {"dimension": "category"}),
        ),
        output="share",
    )
    assert Op.CONTRIBUTION in plan.operations


@pytest.mark.parametrize("steps,output", [
    ((PlanStep("a", Op.FILTER, ("missing",)),), "a"),
    ((PlanStep("a", Op.FILTER, ("data",)), PlanStep("a", Op.GROUP, ("data",))), "a"),
    ((PlanStep("a", Op.FILTER, ("b",)), PlanStep("b", Op.FILTER, ("a",))), "b"),
    ((PlanStep("a", Op.FILTER, ("data",)),), "missing"),
    ((PlanStep("a", Op.FILTER, ()),), "a"),
])
def test_invalid_graphs_fail_closed(steps, output):
    with pytest.raises(ValueError):
        AnalyticalPlan(sources=("data",), steps=steps, output=output)


def test_duplicate_source_and_step_identifiers_fail():
    with pytest.raises(ValueError):
        AnalyticalPlan(
            sources=("data", "data"),
            steps=(PlanStep("a", Op.FILTER, ("data",)),), output="a",
        )
    with pytest.raises(ValueError):
        AnalyticalPlan(
            sources=("data",),
            steps=(PlanStep("data", Op.FILTER, ("data",)),), output="data",
        )


@pytest.mark.parametrize("kwargs", [
    {"id": ""},
    {"operation": "unknown"},
    {"inputs": ("data", "data")},
    {"inputs": ("",)},
    {"parameters": []},
])
def test_invalid_steps_fail_closed(kwargs):
    values = dict(id="filter", operation=Op.FILTER, inputs=("data",))
    values.update(kwargs)
    with pytest.raises(ValueError):
        PlanStep(**values)
