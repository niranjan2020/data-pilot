"""Batch scoring regression tests: blocked and absent evidence never pass."""
from dataclasses import replace

import pytest

from datapilot.application.services.analytical_evaluation import (
    AnalyticalEvaluationCase, AnalyticalEvaluationResult,
)
from datapilot.application.services.analytical_golden_questions import (
    GoldenAnalyticalQuestion, GoldenCaseStatus,
)
from datapilot.application.services.analytical_golden_readiness import GoldenCatalogReadiness
from datapilot.application.services.analytical_golden_batch import (
    EvaluationDisposition as Status, score_golden_batch,
)
from datapilot.application.services.analytical_plan import AnalyticalOperation as Op


def evidence():
    cases = tuple(
        GoldenAnalyticalQuestion(
            expectation=AnalyticalEvaluationCase(
                case_id=f"case-{i}", question=f"Question {i}",
                expected_operations=(Op.GROUP,),
            ),
            domain="test", status=GoldenCaseStatus.SUPPORTED,
        )
        for i in range(4)
    )
    readiness = (
        GoldenCatalogReadiness("case-0", True, ()),
        GoldenCatalogReadiness("case-1", True, ()),
        GoldenCatalogReadiness("case-2", False, ("unpublished_metric",)),
        GoldenCatalogReadiness("case-3", True, ()),
    )
    predictions = (
        AnalyticalEvaluationResult("case-0", True, ()),
        AnalyticalEvaluationResult("case-1", False, ("metric_mismatch",)),
    )
    return cases, readiness, predictions


def test_report_distinguishes_all_four_outcomes():
    report = score_golden_batch(*evidence())
    assert (report.total, report.passed, report.failed, report.blocked,
            report.not_evaluated, report.evaluated) == (4, 1, 1, 1, 1, 2)
    assert tuple(item.disposition for item in report.cases) == (
        Status.PASSED, Status.FAILED, Status.BLOCKED, Status.NOT_EVALUATED,
    )


@pytest.mark.parametrize("index", range(4))
def test_report_preserves_original_case_order(index):
    cases, readiness, predictions = evidence()
    report = score_golden_batch(cases, tuple(reversed(readiness)), tuple(reversed(predictions)))
    assert report.cases[index].case_id == cases[index].expectation.case_id


@pytest.mark.parametrize("index", range(4))
def test_missing_readiness_evidence_fails_closed(index):
    cases, readiness, predictions = evidence()
    with pytest.raises(ValueError, match="exactly"):
        score_golden_batch(cases, readiness[:index] + readiness[index + 1:], predictions)


@pytest.mark.parametrize("index", range(2))
def test_duplicate_prediction_evidence_rejected(index):
    cases, readiness, predictions = evidence()
    with pytest.raises(ValueError, match="Duplicate"):
        score_golden_batch(cases, readiness, predictions + (predictions[index],))


@pytest.mark.parametrize("index", range(4))
def test_duplicate_readiness_evidence_rejected(index):
    cases, readiness, predictions = evidence()
    with pytest.raises(ValueError, match="Duplicate"):
        score_golden_batch(cases, readiness + (readiness[index],), predictions)


@pytest.mark.parametrize("index", range(4))
def test_blocked_cases_ignore_claimed_prediction_success(index):
    cases, readiness, predictions = evidence()
    modified = list(readiness)
    modified[index] = GoldenCatalogReadiness(f"case-{index}", False, ("not_published",))
    supplied = predictions + (AnalyticalEvaluationResult(f"case-{index}", True, ()),) if index > 1 else predictions
    report = score_golden_batch(cases, tuple(modified), supplied)
    assert report.cases[index].disposition is Status.BLOCKED


@pytest.mark.parametrize("bad", [None, [], ("bad",)])
@pytest.mark.parametrize("argument", [0, 1, 2])
def test_invalid_evidence_collection_rejected(argument, bad):
    args = list(evidence())
    args[argument] = bad
    with pytest.raises(ValueError):
        score_golden_batch(*args)


@pytest.mark.parametrize("status", [True, False])
def test_inconsistent_readiness_evidence_rejected(status):
    cases, readiness, predictions = evidence()
    changed = (GoldenCatalogReadiness("case-0", status, ("reason",) if status else ()),) + readiness[1:]
    with pytest.raises(ValueError, match="Inconsistent"):
        score_golden_batch(cases, changed, predictions)


@pytest.mark.parametrize("status", [True, False])
def test_inconsistent_prediction_evidence_rejected(status):
    cases, readiness, predictions = evidence()
    changed = (AnalyticalEvaluationResult("case-0", status, ("reason",) if status else ()),) + predictions[1:]
    with pytest.raises(ValueError, match="Inconsistent"):
        score_golden_batch(cases, readiness, changed)


def test_unknown_prediction_id_rejected():
    cases, readiness, predictions = evidence()
    with pytest.raises(ValueError, match="Unknown"):
        score_golden_batch(cases, readiness, predictions + (
            AnalyticalEvaluationResult("unknown", True, ()),
        ))


def test_empty_batch_has_zero_denominators():
    report = score_golden_batch((), (), ())
    assert (report.total, report.evaluated, report.passed) == (0, 0, 0)


def test_prediction_for_blocked_case_does_not_change_coverage():
    cases, readiness, predictions = evidence()
    report = score_golden_batch(cases, readiness, predictions + (
        AnalyticalEvaluationResult("case-2", True, ()),
    ))
    assert report.blocked == 1
    assert report.passed == 1
