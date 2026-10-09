import pytest

from datapilot.application.services.analytical_context_adapter import (
    build_published_analytical_context,
)
from datapilot.application.services.analytical_plan import (
    AnalyticalOperation as Op, AnalyticalPlan, PlanStep,
)
from datapilot.application.services.published_analytical_context import (
    bind_published_analytical_plan,
)


def test_authorized_snapshot_binds_governed_metric():
    context = build_published_analytical_context(
        datasource="sales",
        metrics=[{"datasource": "sales", "name": "Revenue", "id": 5}],
        dimensions=[],
        is_published=lambda kind, record: kind == "metric" and record["id"] == 5,
    )
    plan = AnalyticalPlan(
        sources=("orders",),
        steps=(PlanStep("sum", Op.AGGREGATE, ("orders",), {"metric": "Revenue"}),),
        output="sum",
    )
    assert bind_published_analytical_plan(
        plan, datasource="sales", context=context,
    ).references[0].name == "Revenue"


def test_unpublished_metadata_is_rejected():
    with pytest.raises(ValueError, match="Unpublished"):
        build_published_analytical_context(
            datasource="sales",
            metrics=[{"datasource": "sales", "name": "Revenue"}],
            dimensions=[],
            is_published=lambda kind, record: False,
        )


def test_cross_datasource_metadata_is_rejected_before_authorization():
    with pytest.raises(ValueError, match="Datasource mismatch"):
        build_published_analytical_context(
            datasource="sales",
            metrics=[{"datasource": "fleet", "name": "Capacity"}],
            dimensions=[],
            is_published=lambda kind, record: True,
        )


def test_missing_authorization_checker_is_rejected():
    with pytest.raises(ValueError, match="publication checker"):
        build_published_analytical_context(
            datasource="sales", metrics=[], dimensions=[],
            is_published=None,
        )


def test_snapshot_does_not_retain_untrusted_fields_or_mutations():
    source = {"datasource": "sales", "name": "Revenue", "id": 5, "expression": "unsafe"}
    context = build_published_analytical_context(
        datasource="sales", metrics=[source], dimensions=[],
        is_published=lambda kind, record: True,
    )
    source["name"] = "Modified"
    assert context.metrics[0] == {
        "name": "Revenue", "datasource": "sales", "published": True,
    }


def test_authorization_applies_to_dimensions_and_time_roles():
    with pytest.raises(ValueError, match="Unpublished time_dimension"):
        build_published_analytical_context(
            datasource="sales", metrics=[], dimensions=[],
            time_dimensions=[{"datasource": "sales", "name": "Order Date"}],
            is_published=lambda kind, record: kind != "time_dimension",
        )
