"""Fail-closed batch scoring of governed analytical evaluations.

Only independently supplied predictions can be scored. Missing predictions,
unpublished semantics, and pending capabilities are never counted as passes.
This module performs no SQL execution or provider calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from datapilot.application.services.analytical_evaluation import (
    AnalyticalEvaluationResult,
)
from datapilot.application.services.analytical_golden_questions import (
    GoldenAnalyticalQuestion,
)
from datapilot.application.services.analytical_golden_readiness import (
    GoldenCatalogReadiness,
)


class EvaluationDisposition(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class ScoredGoldenCase:
    case_id: str
    disposition: EvaluationDisposition
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class GoldenBatchReport:
    total: int
    passed: int
    failed: int
    blocked: int
    not_evaluated: int
    evaluated: int
    cases: tuple[ScoredGoldenCase, ...]


def score_golden_batch(
    cases: tuple[GoldenAnalyticalQuestion, ...],
    readiness: tuple[GoldenCatalogReadiness, ...],
    predictions: tuple[AnalyticalEvaluationResult, ...],
) -> GoldenBatchReport:
    """Score provided evaluation evidence without making accuracy claims for gaps.

    A failed prediction is different from an absent prediction or unpublished
    catalog metadata. All three are explicitly represented in the report.
    """
    if not isinstance(cases, tuple) or any(
        not isinstance(item, GoldenAnalyticalQuestion) for item in cases
    ):
        raise ValueError("Cases must be a typed tuple")
    if not isinstance(readiness, tuple) or any(
        not isinstance(item, GoldenCatalogReadiness) for item in readiness
    ):
        raise ValueError("Readiness must be a typed tuple")
    if not isinstance(predictions, tuple) or any(
        not isinstance(item, AnalyticalEvaluationResult) for item in predictions
    ):
        raise ValueError("Predictions must be a typed tuple")
    ids = tuple(item.expectation.case_id for item in cases)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate golden case ids")
    ready_ids = tuple(item.case_id for item in readiness)
    prediction_ids = tuple(item.case_id for item in predictions)
    if len(ready_ids) != len(set(ready_ids)) or len(prediction_ids) != len(set(prediction_ids)):
        raise ValueError("Duplicate evaluation evidence ids")
    if set(ready_ids) != set(ids):
        raise ValueError("Readiness evidence must cover exactly the golden cases")
    if not set(prediction_ids).issubset(set(ids)):
        raise ValueError("Unknown prediction case id")
    if any(
        (item.ready and item.reasons) or (not item.ready and not item.reasons)
        for item in readiness
    ):
        raise ValueError("Inconsistent readiness evidence")
    if any(
        (item.passed and item.failures) or (not item.passed and not item.failures)
        for item in predictions
    ):
        raise ValueError("Inconsistent prediction evidence")

    ready_by_id = {item.case_id: item for item in readiness}
    prediction_by_id = {item.case_id: item for item in predictions}
    scored = []
    for case_id in ids:
        gate = ready_by_id[case_id]
        prediction = prediction_by_id.get(case_id)
        if not gate.ready:
            scored.append(ScoredGoldenCase(case_id, EvaluationDisposition.BLOCKED, gate.reasons))
        elif prediction is None:
            scored.append(ScoredGoldenCase(
                case_id, EvaluationDisposition.NOT_EVALUATED, ("prediction_missing",),
            ))
        elif prediction.passed:
            scored.append(ScoredGoldenCase(case_id, EvaluationDisposition.PASSED, ()))
        else:
            scored.append(ScoredGoldenCase(
                case_id, EvaluationDisposition.FAILED, prediction.failures,
            ))
    scored_tuple = tuple(scored)
    counts = {
        status: sum(item.disposition is status for item in scored_tuple)
        for status in EvaluationDisposition
    }
    passed = counts[EvaluationDisposition.PASSED]
    failed = counts[EvaluationDisposition.FAILED]
    return GoldenBatchReport(
        total=len(scored_tuple), passed=passed, failed=failed,
        blocked=counts[EvaluationDisposition.BLOCKED],
        not_evaluated=counts[EvaluationDisposition.NOT_EVALUATED],
        evaluated=passed + failed, cases=scored_tuple,
    )
