"""Evaluation contract tests for independently specified analytical expectations."""
from dataclasses import replace

import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_plan import AnalyticalOperation as Op, AnalyticalPlan, PlanStep
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan
from datapilot.application.services.unified_analytical_binding import unify_physical_analytical_plan
from datapilot.application.services.analytical_sql_compiler import (
    GovernedMetricSource, compile_governed_analytical_plan,
)
from datapilot.application.services.analytical_evaluation import (
    AnalyticalEvaluationCase, evaluate_analytical_case,
)


def fixture(domain="sales", *, with_filter=True, with_threshold=True):
    schema, table = ("Sales", "OrderDetail") if domain == "sales" else ("astra", "vessel")
    dims = (
        AnalyticalDimension("Category", 1, table, schema, table, "category_code"),
        AnalyticalDimension("Group", 1, table, schema, table, "group_code"),
    )
    steps = []
    previous = "source"
    if with_filter:
        steps.append(PlanStep("filter", Op.FILTER, (previous,), {
            "dimension": f"{table}.Category", "operator": "IN", "values": ("O", "TO"),
        }))
        previous = "filter"
    steps.extend((
        PlanStep("group", Op.GROUP, (previous,), {"dimension": f"{table}.Group"}),
        PlanStep("aggregate", Op.AGGREGATE, ("group",), {"metric": "Measure"}),
    ))
    previous = "aggregate"
    if with_threshold:
        steps.append(PlanStep("threshold", Op.THRESHOLD, (previous,), {
            "metric": "Measure", "operator": "GT", "value": 5,
        }))
        previous = "threshold"
    steps.extend((
        PlanStep("sort", Op.SORT, (previous,), {"metric": "Measure", "direction": "DESC"}),
        PlanStep("limit", Op.LIMIT, ("sort",), {"count": 10}),
    ))
    plan = AnalyticalPlan(sources=("source",), steps=tuple(steps), output="limit")
    bound = bind_analytical_plan(
        plan,
        approved_dimensions=[{"name": f"{table}.Category"}, {"name": f"{table}.Group"}],
        approved_metrics=[{"name": "Measure"}],
    )
    physical = unify_physical_analytical_plan(
        bound, published_dimensions=dims,
        published_metrics=({"name": "Measure", "entity_id": 1, "attribute_name": "id",
                            "aggregation": "COUNT", "calculation_expression": None},),
        published_time_dimensions=(),
    )
    source = GovernedMetricSource(1, schema, table, "id")
    compiled = compile_governed_analytical_plan(
        physical, metric_source=source, published_dimensions=dims,
    )
    ops = ((Op.FILTER,) if with_filter else ()) + (Op.GROUP, Op.AGGREGATE) + (
        (Op.THRESHOLD,) if with_threshold else ()
    ) + (Op.SORT, Op.LIMIT)
    params = (("O", "TO") if with_filter else ()) + ((5,) if with_threshold else ())
    names = ((f"{table}.Category",) if with_filter else ()) + (f"{table}.Group",)
    metrics = ("Measure",) * (2 + int(with_threshold))
    case = AnalyticalEvaluationCase(
        case_id=f"{domain}-{with_filter}-{with_threshold}",
        question="Group by category and count matching records",
        expected_operations=ops, expected_dimensions=names,
        expected_metrics=metrics, expected_parameters=params,
        expected_source=(schema, table),
    )
    return case, physical, compiled, source, dims


@pytest.mark.parametrize("domain", ["sales", "vessel"])
@pytest.mark.parametrize("with_filter", [False, True])
@pytest.mark.parametrize("with_threshold", [False, True])
def test_cross_domain_evaluation_contract(domain, with_filter, with_threshold):
    case, physical, compiled, source, dims = fixture(
        domain, with_filter=with_filter, with_threshold=with_threshold,
    )
    result = evaluate_analytical_case(
        case, physical, compiled, metric_source=source, published_dimensions=dims,
    )
    assert result.passed, result.failures


@pytest.mark.parametrize("change,expected_failure", [
    ({"expected_operations": (Op.GROUP, Op.AGGREGATE, Op.SORT, Op.LIMIT)}, "operation_mismatch"),
    ({"expected_dimensions": ("incorrect.dimension",)}, "dimension_mismatch"),
    ({"expected_metrics": ("WrongMetric",)}, "metric_mismatch"),
    ({"expected_parameters": ("TO", "O", 5)}, "parameter_mismatch"),
    ({"expected_source": ("public", "other")}, "source_mismatch"),
])
@pytest.mark.parametrize("domain", ["sales", "vessel"])
def test_evaluation_rejects_semantic_mismatch(domain, change, expected_failure):
    case, physical, compiled, source, dims = fixture(domain)
    altered = replace(case, **change)
    result = evaluate_analytical_case(
        altered, physical, compiled, metric_source=source, published_dimensions=dims,
    )
    assert not result.passed
    assert expected_failure in result.failures


@pytest.mark.parametrize("domain", ["sales", "vessel"])
@pytest.mark.parametrize("tamper", [
    lambda q: replace(q, sql=q.sql + " -- modified"),
    lambda q: replace(q, parameters=("O", "TO", 6)),
    lambda q: replace(q, dialect="sqlite"),
])
def test_evaluation_rejects_sql_or_binding_tampering(domain, tamper):
    case, physical, compiled, source, dims = fixture(domain)
    result = evaluate_analytical_case(
        case, physical, tamper(compiled), metric_source=source, published_dimensions=dims,
    )
    assert not result.passed
    assert "sql_verification_failed" in result.failures


@pytest.mark.parametrize("field,value", [
    ("case_id", ""), ("question", ""), ("expected_operations", ()),
    ("expected_operations", ("filter",)), ("expected_dimensions", []),
    ("expected_metrics", []), ("expected_parameters", []),
    ("expected_source", ("only_schema",)),
])
def test_invalid_evaluation_contract_rejected(field, value):
    arguments = {
        "case_id": "case",
        "question": "Question",
        "expected_operations": (Op.GROUP,),
    }
    arguments[field] = value
    with pytest.raises(ValueError):
        AnalyticalEvaluationCase(**arguments)
