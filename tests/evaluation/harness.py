"""Provider-independent evaluation models and result comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from datapilot.domain.query import QueryResponse


@dataclass(frozen=True)
class EvaluationExpectation:
    tables: tuple[str, ...] = ()
    row_count: int | None = None
    scalar: Any | None = None
    rows: tuple[tuple[Any, ...], ...] = ()
    datasets: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    relationships: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    excluded_datasets: tuple[str, ...] = ()
    excluded_entities: tuple[str, ...] = ()
    excluded_metrics: tuple[str, ...] = ()
    require_completed: bool = False
    require_sql: bool = False
    expected_status: str | None = None
    clarification_kind: str | None = None
    clarification_options: tuple[str, ...] = ()
    sql_contains: tuple[str, ...] = ()
    sql_excludes: tuple[str, ...] = ()
    required_correctness_codes: tuple[str, ...] = ()
    forbidden_correctness_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    question: str
    expected: EvaluationExpectation
    conversation_id: str | None = None


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    passed: bool
    failures: tuple[str, ...] = ()
    duration_ms: float | None = None


@dataclass
class EvaluationSummary:
    results: list[EvaluationResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(result.passed for result in self.results)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def durations_ms(self) -> list[float]:
        return [result.duration_ms for result in self.results if result.duration_ms is not None]

    def percentile_ms(self, percentile: float) -> float | None:
        values = sorted(self.durations_ms)
        if not values:
            return None
        if len(values) == 1:
            return values[0]
        position = (len(values) - 1) * percentile
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        fraction = position - lower
        return values[lower] + (values[upper] - values[lower]) * fraction

    @property
    def p50_ms(self) -> float | None:
        return self.percentile_ms(0.50)

    @property
    def p95_ms(self) -> float | None:
        return self.percentile_ms(0.95)


def normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def evaluate_case(
    case: EvaluationCase,
    *,
    rows: Sequence[Sequence[Any]],
    affected_tables: Iterable[str] = (),
) -> EvaluationResult:
    expected = case.expected
    normalized_rows = tuple(tuple(normalize_value(v) for v in row) for row in rows)
    failures: list[str] = []

    if expected.tables:
        actual_tables = {table.lower() for table in affected_tables}
        missing = sorted({table.lower() for table in expected.tables} - actual_tables)
        if missing:
            failures.append(f"missing expected tables: {', '.join(missing)}")

    if expected.row_count is not None and len(normalized_rows) != expected.row_count:
        failures.append(
            f"expected {expected.row_count} rows, got {len(normalized_rows)}"
        )

    if expected.scalar is not None:
        actual = normalized_rows[0][0] if normalized_rows and normalized_rows[0] else None
        if normalize_value(expected.scalar) != actual:
            failures.append(f"expected scalar {expected.scalar!r}, got {actual!r}")

    if expected.rows:
        expected_rows = tuple(
            tuple(normalize_value(v) for v in row) for row in expected.rows
        )
        if normalized_rows != expected_rows:
            failures.append(f"expected rows {expected_rows!r}, got {normalized_rows!r}")

    return EvaluationResult(
        case_id=case.id,
        passed=not failures,
        failures=tuple(failures),
    )


def evaluate_query_response(
    case: EvaluationCase,
    response: QueryResponse,
) -> EvaluationResult:
    """Evaluate semantic selection separately from optional result ground truth."""
    expected = case.expected
    failures: list[str] = []
    trace = response.trace

    if expected.expected_status is not None and response.status != expected.expected_status:
        failures.append(f"expected status {expected.expected_status!r}, got {response.status!r}")
    if expected.require_completed and response.status != "completed":
        failures.append(f"expected completed status, got {response.status!r}")
    if expected.clarification_kind is not None:
        if response.clarification is None:
            failures.append("expected structured clarification")
        elif response.clarification.kind != expected.clarification_kind:
            failures.append(
                f"expected clarification kind {expected.clarification_kind!r}, "
                f"got {response.clarification.kind!r}"
            )
    if expected.clarification_options:
        if response.clarification is None:
            failures.append("expected clarification options")
        else:
            actual_options = {option.value for option in response.clarification.options}
            missing_options = sorted(set(expected.clarification_options) - actual_options)
            if missing_options:
                failures.append(
                    "missing clarification options: " + ", ".join(missing_options)
                )
    if expected.require_sql and not response.sql:
        failures.append("expected generated SQL")
    normalized_sql = (response.sql or "").lower()
    for fragment in expected.sql_contains:
        if fragment.lower() not in normalized_sql:
            failures.append(f"SQL missing expected fragment: {fragment!r}")
    for fragment in expected.sql_excludes:
        if fragment.lower() in normalized_sql:
            failures.append(f"SQL contains forbidden fragment: {fragment!r}")

    if any((
        expected.datasets, expected.entities, expected.relationships,
        expected.metrics, expected.excluded_datasets,
        expected.excluded_entities, expected.excluded_metrics,
    )) and trace is None:
        failures.append("query trace is required for semantic evaluation")
    elif trace is not None:
        checks = (
            ("datasets", expected.datasets, trace.governed_datasets),
            ("entities", expected.entities, trace.governed_entities),
            ("relationships", expected.relationships, trace.governed_relationships),
            ("metrics", expected.metrics, trace.governed_metrics),
        )
        for label, wanted, actual in checks:
            missing = sorted(set(wanted) - set(actual))
            if missing:
                failures.append(f"missing expected {label}: {', '.join(missing)}")

        exclusions = (
            ("datasets", expected.excluded_datasets, trace.governed_datasets),
            ("entities", expected.excluded_entities, trace.governed_entities),
            ("metrics", expected.excluded_metrics, trace.governed_metrics),
        )
        for label, forbidden, actual in exclusions:
            leaked = sorted(set(forbidden) & set(actual))
            if leaked:
                failures.append(f"unexpected {label}: {', '.join(leaked)}")

    if expected.required_correctness_codes or expected.forbidden_correctness_codes:
        if trace is None:
            failures.append("query trace is required for correctness evaluation")
        else:
            actual_codes = {
                str(check.get("code"))
                for check in trace.correctness_checks
                if check.get("code")
            }
            missing_codes = sorted(set(expected.required_correctness_codes) - actual_codes)
            if missing_codes:
                failures.append(
                    "missing expected correctness checks: " + ", ".join(missing_codes)
                )
            forbidden_codes = sorted(set(expected.forbidden_correctness_codes) & actual_codes)
            if forbidden_codes:
                failures.append(
                    "unexpected correctness checks: " + ", ".join(forbidden_codes)
                )

    # Result assertions remain optional and independent from semantic correctness.
    if response.status == "completed" and response.result is not None:
        rows = response.result.get("rows", []) if isinstance(response.result, Mapping) else []
        affected = response.result.get("affected_tables", []) if isinstance(response.result, Mapping) else []
        result_eval = evaluate_case(case, rows=rows, affected_tables=affected)
        failures.extend(result_eval.failures)

    return EvaluationResult(case_id=case.id, passed=not failures, failures=tuple(failures))
