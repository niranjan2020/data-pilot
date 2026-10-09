import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_physical_binding import (
    attach_physical_dimensions,
)
from datapilot.application.services.analytical_plan import (
    AnalyticalOperation, AnalyticalPlan, PlanStep,
)
from datapilot.application.services.analytical_plan_binding import (
    bind_analytical_plan,
)


def dimension(entity_id=1, entity="Customer", name="Region", column="RegionCode"):
    return AnalyticalDimension(
        name=name, entity_id=entity_id, entity_name=entity,
        schema_name="Sales", table_name=entity, column_name=column,
    )


def bound(name="Customer.Region"):
    plan = AnalyticalPlan(
        sources=("sales",),
        steps=(PlanStep(
            id="group", operation=AnalyticalOperation.GROUP,
            inputs=("sales",), parameters={"dimension": name},
        ),),
        output="group",
    )
    return bind_analytical_plan(
        plan, approved_metrics=[],
        approved_dimensions=[{"name": name}],
    )


def test_physical_mapping_preserves_governed_column():
    result = attach_physical_dimensions(
        bound(), published_dimensions=(dimension(),),
    )
    mapping = result.dimensions[0]
    assert (mapping.schema_name, mapping.table_name, mapping.column_name) == (
        "Sales", "Customer", "RegionCode",
    )
    assert mapping.semantic_name == "Customer.Region"


def test_unqualified_name_uses_approved_mapping():
    result = attach_physical_dimensions(
        bound("Region"), published_dimensions=(dimension(),),
    )
    assert result.dimensions[0].column_name == "RegionCode"


def test_unpublished_dimension_is_rejected():
    with pytest.raises(ValueError, match="Unknown"):
        attach_physical_dimensions(
            bound(), published_dimensions=(),
        )


def test_ambiguous_unqualified_mapping_is_rejected():
    with pytest.raises(ValueError, match="ambiguous"):
        attach_physical_dimensions(
            bound("Region"),
            published_dimensions=(dimension(), dimension(2, "Supplier")),
        )


def test_qualified_mapping_selects_correct_owner():
    result = attach_physical_dimensions(
        bound("Supplier.Region"),
        published_dimensions=(dimension(), dimension(2, "Supplier", column="Territory")),
    )
    assert result.dimensions[0].column_name == "Territory"


def test_mapping_does_not_use_plan_supplied_column():
    result = attach_physical_dimensions(
        bound(), published_dimensions=(dimension(column="ApprovedColumn"),),
    )
    assert result.dimensions[0].column_name == "ApprovedColumn"


def test_invalid_bound_plan_is_rejected():
    with pytest.raises(ValueError, match="governed"):
        attach_physical_dimensions(None, published_dimensions=(dimension(),))
