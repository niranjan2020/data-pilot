import pytest

from datapilot.application.services.analytical_measure_time_binding import (
    attach_physical_measures_and_time,
)
from datapilot.application.services.analytical_plan import (
    AnalyticalOperation, AnalyticalPlan, PlanStep,
)
from datapilot.application.services.analytical_plan_binding import bind_analytical_plan


def bound():
    plan = AnalyticalPlan(
        sources=("sales",),
        steps=(
            PlanStep(id="aggregate", operation=AnalyticalOperation.AGGREGATE,
                     inputs=("sales",), parameters={"metric": "Revenue"}),
            PlanStep(id="time", operation=AnalyticalOperation.TIME_WINDOW,
                     inputs=("aggregate",), parameters={"role": "Order Date"}),
        ),
        output="time",
    )
    return bind_analytical_plan(
        plan,
        approved_metrics=[{"name": "Revenue"}],
        approved_dimensions=[],
        approved_time_dimensions=[{"name": "Order Date"}],
    )


def metric(**changes):
    record = {
        "name": "Revenue", "entity_id": 1, "attribute_name": "LineTotal",
        "aggregation": "SUM", "calculation_expression": None,
    }
    record.update(changes)
    return record


def time(**changes):
    record = {
        "name": "Order Date", "entity_id": 1, "column_name": "OrderDate",
        "role": "order_date", "grain": "day",
    }
    record.update(changes)
    return record


def attach(metrics=None, times=None):
    return attach_physical_measures_and_time(
        bound(),
        published_metrics=(metric(),) if metrics is None else metrics,
        published_time_dimensions=(time(),) if times is None else times,
    )


def test_metric_binding_preserves_aggregation_and_attribute():
    result = attach()
    assert (result.metrics[0].aggregation, result.metrics[0].attribute_name) == (
        "SUM", "LineTotal",
    )


def test_time_binding_preserves_role_column_and_grain():
    result = attach()
    assert (result.time_dimensions[0].role, result.time_dimensions[0].column_name,
            result.time_dimensions[0].grain) == ("order_date", "OrderDate", "day")


def test_metric_expression_is_opaque_catalog_data():
    result = attach(metrics=(metric(attribute_name=None, calculation_expression="Price * Quantity"),))
    assert result.metrics[0].calculation_expression == "Price * Quantity"


def test_missing_metric_is_rejected():
    with pytest.raises(ValueError, match="Missing approved metric"):
        attach(metrics=())


def test_missing_time_dimension_is_rejected():
    with pytest.raises(ValueError, match="Missing approved time_dimension"):
        attach(times=())


def test_duplicate_metric_names_are_rejected():
    with pytest.raises(ValueError, match="Ambiguous"):
        attach(metrics=(metric(), metric()))


def test_incomplete_metric_is_rejected():
    with pytest.raises(ValueError, match="requires a governed"):
        attach(metrics=(metric(attribute_name=None),))


def test_incomplete_time_mapping_is_rejected():
    with pytest.raises(ValueError, match="Incomplete"):
        attach(times=(time(column_name=None),))


def test_invalid_entity_id_is_rejected():
    with pytest.raises(ValueError, match="entity identifier"):
        attach(metrics=(metric(entity_id=True),))


def test_invalid_bound_plan_is_rejected():
    with pytest.raises(ValueError, match="governed"):
        attach_physical_measures_and_time(
            None, published_metrics=(), published_time_dimensions=(),
        )
