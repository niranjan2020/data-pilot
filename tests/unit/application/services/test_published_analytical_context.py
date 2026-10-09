import pytest

from datapilot.application.services.analytical_plan import (
    AnalyticalOperation as Op, AnalyticalPlan, PlanStep,
)
from datapilot.application.services.published_analytical_context import (
    PublishedSemanticContext, bind_published_analytical_plan,
)


def plan():
    return AnalyticalPlan(
        sources=("orders",),
        steps=(PlanStep("total", Op.AGGREGATE, ("orders",), {"metric": "Revenue"}),),
        output="total",
    )


def record(name="Revenue", datasource="sales", published=True):
    return {"name": name, "datasource": datasource, "published": published}


def test_published_metric_from_matching_datasource_binds():
    context = PublishedSemanticContext(
        datasource="sales", metrics=(record(),), dimensions=(),
    )
    bound = bind_published_analytical_plan(plan(), datasource="sales", context=context)
    assert bound.references[0].name == "Revenue"


def test_cross_datasource_metric_rejected():
    with pytest.raises(ValueError, match="Cross-datasource"):
        PublishedSemanticContext(
            datasource="sales", metrics=(record(datasource="fleet"),), dimensions=(),
        )


def test_unpublished_metric_rejected():
    with pytest.raises(ValueError, match="Unpublished"):
        PublishedSemanticContext(
            datasource="sales", metrics=(record(published=False),), dimensions=(),
        )


def test_missing_publication_status_is_not_assumed():
    with pytest.raises(ValueError, match="Unpublished"):
        PublishedSemanticContext(
            datasource="sales",
            metrics=({"name": "Revenue", "datasource": "sales"},),
            dimensions=(),
        )


def test_requested_datasource_must_match_context():
    context = PublishedSemanticContext(
        datasource="sales", metrics=(record(),), dimensions=(),
    )
    with pytest.raises(ValueError, match="does not match"):
        bind_published_analytical_plan(plan(), datasource="fleet", context=context)


def test_unpublished_dimension_rejected_even_when_unused():
    with pytest.raises(ValueError, match="Unpublished"):
        PublishedSemanticContext(
            datasource="sales", metrics=(record(),),
            dimensions=(record("Customer", published=False),),
        )


def test_published_time_dimension_requires_matching_datasource():
    with pytest.raises(ValueError, match="Cross-datasource"):
        PublishedSemanticContext(
            datasource="sales", metrics=(record(),), dimensions=(),
            time_dimensions=(record("Order Date", datasource="fleet"),),
        )


def test_unknown_metric_still_fails_binding():
    context = PublishedSemanticContext(
        datasource="sales", metrics=(record(name="Units"),), dimensions=(),
    )
    with pytest.raises(ValueError, match="Unresolved"):
        bind_published_analytical_plan(plan(), datasource="sales", context=context)
