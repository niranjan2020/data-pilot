"""Readiness validation against published, datasource-scoped semantic metadata."""
from dataclasses import replace

import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_evaluation import AnalyticalEvaluationCase
from datapilot.application.services.analytical_golden_questions import (
    GoldenAnalyticalQuestion, GoldenCaseStatus,
)
from datapilot.application.services.analytical_golden_readiness import validate_golden_catalog_readiness
from datapilot.application.services.analytical_plan import AnalyticalOperation as Op
from datapilot.application.services.published_analytical_context import PublishedSemanticContext


def setup(*, domain="sales", status=GoldenCaseStatus.SUPPORTED):
    schema, table, source = (
        ("Sales", "OrderDetail", "adventureworks") if domain == "sales"
        else ("astra", "vessel", "astra")
    )
    case = GoldenAnalyticalQuestion(
        expectation=AnalyticalEvaluationCase(
            case_id=f"{domain}-01", question="Count records by group",
            expected_operations=(Op.GROUP, Op.AGGREGATE, Op.SORT, Op.LIMIT),
            expected_dimensions=(f"{table}.Group",),
            expected_metrics=("Measure", "Measure"),
            expected_source=(schema, table),
        ),
        domain=source, status=status,
        required_capabilities=("join",) if status is GoldenCaseStatus.PENDING else (),
    )
    context = PublishedSemanticContext(
        datasource=source,
        metrics=({"id": 1, "name": "Measure", "published": True, "datasource": source},),
        dimensions=(), time_dimensions=(),
    )
    attrs = (AnalyticalDimension("Group", 1, table, schema, table, "group_code"),)
    return case, context, attrs, source


def check(case, context, attrs, datasource):
    return validate_golden_catalog_readiness(
        case, context=context, published_attributes=attrs, datasource=datasource,
    )


@pytest.mark.parametrize("domain", ["sales", "vessel"])
def test_published_semantics_ready(domain):
    result = check(*setup(domain=domain))
    assert result.ready, result.reasons


@pytest.mark.parametrize("domain", ["sales", "vessel"])
def test_pending_capabilities_never_marked_ready(domain):
    result = check(*setup(domain=domain, status=GoldenCaseStatus.PENDING))
    assert not result.ready
    assert "unsupported_capability" in result.reasons


@pytest.mark.parametrize("domain", ["sales", "vessel"])
def test_missing_attribute_publication_rejected(domain):
    case, context, attrs, datasource = setup(domain=domain)
    result = check(case, context, (), datasource)
    assert not result.ready
    assert result.reasons[0].startswith("unpublished_or_ambiguous_dimension:")


@pytest.mark.parametrize("domain", ["sales", "vessel"])
def test_missing_metric_publication_rejected(domain):
    case, context, attrs, datasource = setup(domain=domain)
    context = replace(context, metrics=())
    result = check(case, context, attrs, datasource)
    assert not result.ready
    assert result.reasons[0].startswith("unpublished_or_ambiguous_metric:")


@pytest.mark.parametrize("domain", ["sales", "vessel"])
def test_ambiguous_metric_publication_rejected(domain):
    case, context, attrs, datasource = setup(domain=domain)
    context = replace(context, metrics=context.metrics + (
        {"id": 2, "name": "MEASURE", "published": True, "datasource": datasource},
    ))
    result = check(case, context, attrs, datasource)
    assert not result.ready
    assert any("ambiguous_metric" in reason for reason in result.reasons)


@pytest.mark.parametrize("domain", ["sales", "vessel"])
def test_cross_source_attribute_rejected(domain):
    case, context, attrs, datasource = setup(domain=domain)
    altered = (replace(attrs[0], schema_name="untrusted"),)
    result = check(case, context, altered, datasource)
    assert not result.ready
    assert any("dimension_source_mismatch" in reason for reason in result.reasons)


@pytest.mark.parametrize("domain", ["sales", "vessel"])
def test_cross_datasource_context_rejected(domain):
    case, context, attrs, datasource = setup(domain=domain)
    result = check(case, context, attrs, "another-datasource")
    assert not result.ready
    assert result.reasons == ("datasource_mismatch",)


@pytest.mark.parametrize("domain", ["sales", "vessel"])
def test_duplicate_attribute_is_ambiguous(domain):
    case, context, attrs, datasource = setup(domain=domain)
    result = check(case, context, attrs + attrs, datasource)
    assert not result.ready
    assert any("ambiguous_dimension" in reason for reason in result.reasons)


@pytest.mark.parametrize("domain", ["sales", "vessel"])
def test_unknown_semantic_reference_rejected(domain):
    case, context, attrs, datasource = setup(domain=domain)
    altered = replace(case, expectation=replace(
        case.expectation, expected_dimensions=("Missing.Dimension",),
        expected_metrics=("Unknown",),
    ))
    result = check(altered, context, attrs, datasource)
    assert not result.ready
    assert len(result.reasons) == 2


@pytest.mark.parametrize("invalid", [None, [], ["not-a-dimension"], ("wrong",)])
def test_untrusted_attribute_collection_rejected(invalid):
    case, context, _, datasource = setup()
    with pytest.raises(ValueError):
        check(case, context, invalid, datasource)


def test_missing_context_rejected():
    case, _, attrs, datasource = setup()
    with pytest.raises(ValueError):
        check(case, None, attrs, datasource)


def test_invalid_datasource_rejected():
    case, context, attrs, _ = setup()
    with pytest.raises(ValueError):
        check(case, context, attrs, "")
