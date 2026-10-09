"""Deterministic, datasource-independent analytical evaluation contracts.

This module scores already-bound analytical plans and verified compiled SQL.
It never invokes an LLM, accesses a database, or authorizes execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datapilot.application.services.analytical_plan import AnalyticalOperation
from datapilot.application.services.analytical_sql_compiler import (
    CompiledAnalyticalQuery, GovernedMetricSource,
)
from datapilot.application.services.analytical_sql_verification import (
    verify_governed_analytical_sql,
)
from datapilot.application.services.unified_analytical_binding import UnifiedPhysicalAnalyticalPlan


@dataclass(frozen=True)
class AnalyticalEvaluationCase:
    case_id: str
    question: str
    expected_operations: tuple[AnalyticalOperation, ...]
    expected_dimensions: tuple[str, ...] = ()
    expected_metrics: tuple[str, ...] = ()
    expected_parameters: tuple[Any, ...] = ()
    expected_source: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise ValueError("Evaluation case requires an id")
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError("Evaluation case requires a question")
        if not isinstance(self.expected_operations, tuple) or not self.expected_operations or any(
            not isinstance(op, AnalyticalOperation) for op in self.expected_operations
        ):
            raise ValueError("Evaluation case requires typed analytical operations")
        if not isinstance(self.expected_dimensions, tuple) or not isinstance(self.expected_metrics, tuple):
            raise ValueError("Expected semantic references must be tuples")
        if not isinstance(self.expected_parameters, tuple):
            raise ValueError("Expected parameters must be a tuple")
        if self.expected_source is not None and (
            not isinstance(self.expected_source, tuple)
            or len(self.expected_source) != 2
            or any(not isinstance(v, str) or not v for v in self.expected_source)
        ):
            raise ValueError("Expected source must be schema and table")


@dataclass(frozen=True)
class AnalyticalEvaluationResult:
    case_id: str
    passed: bool
    failures: tuple[str, ...]


def evaluate_analytical_case(
    case: AnalyticalEvaluationCase,
    physical_plan: UnifiedPhysicalAnalyticalPlan,
    compiled: CompiledAnalyticalQuery,
    *,
    metric_source: GovernedMetricSource,
    published_dimensions: tuple = (),
    max_rows: int = 1000,
    max_filters: int = 10,
) -> AnalyticalEvaluationResult:
    """Compare semantic intent and governed SQL without executing a query.

    Failure reasons are stable machine-readable identifiers for reporting.
    A passing case does not prove answer/result-level correctness.
    """
    if not isinstance(case, AnalyticalEvaluationCase):
        raise TypeError("An analytical evaluation case is required")
    if not isinstance(physical_plan, UnifiedPhysicalAnalyticalPlan):
        return AnalyticalEvaluationResult(case.case_id, False, ("invalid_physical_plan",))
    failures: list[str] = []
    actual_operations = tuple(step.operation for step in physical_plan.bound_plan.plan.steps)
    if actual_operations != case.expected_operations:
        failures.append("operation_mismatch")
    actual_dimensions = tuple(binding.semantic_name for binding in physical_plan.dimensions)
    if actual_dimensions != case.expected_dimensions:
        failures.append("dimension_mismatch")
    actual_metrics = tuple(binding.semantic_name for binding in physical_plan.metrics)
    if actual_metrics != case.expected_metrics:
        failures.append("metric_mismatch")
    if not isinstance(compiled, CompiledAnalyticalQuery):
        failures.append("invalid_compiled_query")
    elif type(compiled.parameters) is not tuple or compiled.parameters != case.expected_parameters:
        failures.append("parameter_mismatch")
    if not isinstance(metric_source, GovernedMetricSource):
        failures.append("invalid_metric_source")
    elif case.expected_source is not None and (
        metric_source.schema_name, metric_source.table_name
    ) != case.expected_source:
        failures.append("source_mismatch")
    if "invalid_compiled_query" not in failures and "invalid_metric_source" not in failures:
        verification = verify_governed_analytical_sql(
            physical_plan, compiled, metric_source=metric_source,
            published_dimensions=published_dimensions,
            max_rows=max_rows, max_filters=max_filters,
        )
        if not verification.verified:
            failures.append("sql_verification_failed")
    return AnalyticalEvaluationResult(case.case_id, not failures, tuple(failures))
