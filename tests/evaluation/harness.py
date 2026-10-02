"""Provider-independent evaluation models and result comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class EvaluationExpectation:
    tables: tuple[str, ...] = ()
    row_count: int | None = None
    scalar: Any | None = None
    rows: tuple[tuple[Any, ...], ...] = ()


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    question: str
    expected: EvaluationExpectation


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    passed: bool
    failures: tuple[str, ...] = ()


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
