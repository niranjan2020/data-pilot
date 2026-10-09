"""Read-only golden-question readiness against trusted published semantic metadata.

Caller MUST supply datasource-scoped metadata loaded through persistent
publication grants. This is not a permission check or execution authorization.
"""
from __future__ import annotations

from dataclasses import dataclass

from datapilot.application.services.analytical_dimensions import (
    AnalyticalDimension, resolve_analytical_dimension,
)
from datapilot.application.services.analytical_golden_questions import (
    GoldenAnalyticalQuestion, GoldenCaseStatus,
)
from datapilot.application.services.published_analytical_context import PublishedSemanticContext


@dataclass(frozen=True)
class GoldenCatalogReadiness:
    case_id: str
    ready: bool
    reasons: tuple[str, ...]


def validate_golden_catalog_readiness(
    case: GoldenAnalyticalQuestion,
    *,
    context: PublishedSemanticContext,
    published_attributes: tuple[AnalyticalDimension, ...],
    datasource: str,
) -> GoldenCatalogReadiness:
    """Validate published references, not merely catalog existence.

    Does not infer missing joins, map categorical labels, or evaluate results.
    Unsupported operations remain pending even if metadata exists.
    """
    if not isinstance(case, GoldenAnalyticalQuestion):
        raise ValueError("Golden question is required")
    if not isinstance(context, PublishedSemanticContext):
        raise ValueError("Trusted published context is required")
    if not isinstance(datasource, str) or not datasource.strip():
        raise ValueError("Datasource is required")
    if not isinstance(published_attributes, tuple) or any(
        not isinstance(item, AnalyticalDimension) for item in published_attributes
    ):
        raise ValueError("Published analytical attributes are required")
    if context.datasource.casefold() != datasource.casefold():
        return GoldenCatalogReadiness(case.expectation.case_id, False, ("datasource_mismatch",))

    reasons: list[str] = []
    if case.status is GoldenCaseStatus.PENDING:
        reasons.append("unsupported_capability")
    expected = case.expectation
    for name in dict.fromkeys(expected.expected_dimensions):
        try:
            dimension = resolve_analytical_dimension(published_attributes, name)
        except ValueError:
            reasons.append(f"unpublished_or_ambiguous_dimension:{name}")
            continue
        if expected.expected_source is not None and (
            dimension.schema_name, dimension.table_name
        ) != expected.expected_source:
            reasons.append(f"dimension_source_mismatch:{name}")
    approved_metrics = [
        item["name"].casefold() for item in context.metrics
    ]
    for name in dict.fromkeys(expected.expected_metrics):
        if approved_metrics.count(name.casefold()) != 1:
            reasons.append(f"unpublished_or_ambiguous_metric:{name}")
    # A metric's physical source cannot be inferred from the published
    # name-only context; actual physical binding is a separate gate.
    return GoldenCatalogReadiness(expected.case_id, not reasons, tuple(reasons))
