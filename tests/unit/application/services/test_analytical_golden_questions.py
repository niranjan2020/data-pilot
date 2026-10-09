"""Golden question catalog: coverage, independence and unsupported capability gates."""
from dataclasses import replace
from pathlib import Path
import runpy

import pytest

from datapilot.application.services.analytical_golden_questions import (
    GoldenAnalyticalQuestion, GoldenCaseStatus, summarize_golden_coverage,
)
from datapilot.application.services.analytical_plan import AnalyticalOperation

CATALOG = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "fixtures" / "analytical_golden_questions.py")
)["GOLDEN_QUESTIONS"]


def test_catalog_has_unique_ids_and_explicit_capability_coverage():
    coverage = summarize_golden_coverage(CATALOG)
    assert coverage.total == 16
    assert coverage.supported == 10
    assert coverage.pending == 6
    assert len(coverage.supported_case_ids) == 10
    assert len(coverage.pending_case_ids) == 6


@pytest.mark.parametrize("case", CATALOG, ids=lambda c: c.expectation.case_id)
def test_every_golden_question_has_ground_truth(case):
    expected = case.expectation
    assert expected.question.strip()
    assert expected.expected_operations
    assert expected.expected_source is not None
    assert case.domain in ("adventureworks", "astra")
    if case.status is GoldenCaseStatus.PENDING:
        assert case.required_capabilities
    else:
        assert not case.required_capabilities


@pytest.mark.parametrize("case", CATALOG, ids=lambda c: c.expectation.case_id)
def test_golden_questions_never_claim_result_level_accuracy(case):
    # Catalog stores expectations only; no SQL results, guessed answers or
    # unapproved physical mappings are packaged as evaluation evidence.
    assert not hasattr(case, "actual_result")
    assert not hasattr(case, "generated_sql")
    assert all(isinstance(op, AnalyticalOperation) for op in case.expectation.expected_operations)


@pytest.mark.parametrize("index", range(16))
def test_duplicate_golden_question_ids_fail_closed(index):
    duplicate = replace(
        CATALOG[index], expectation=replace(
            CATALOG[index].expectation, case_id=CATALOG[0].expectation.case_id,
        ),
    )
    with pytest.raises(ValueError, match="Duplicate"):
        summarize_golden_coverage((CATALOG[0], duplicate))


@pytest.mark.parametrize("index", range(16))
def test_pending_question_cannot_be_mislabeled_supported(index):
    case = CATALOG[index]
    if case.status is GoldenCaseStatus.PENDING:
        with pytest.raises(ValueError, match="Supported"):
            replace(case, status=GoldenCaseStatus.SUPPORTED)
    else:
        with pytest.raises(ValueError, match="Pending"):
            replace(case, status=GoldenCaseStatus.PENDING)


@pytest.mark.parametrize("bad", [None, [], ["x"], ("x",)])
def test_invalid_catalog_rejected(bad):
    with pytest.raises(ValueError):
        summarize_golden_coverage(bad)


def test_empty_catalog_has_zero_coverage():
    result = summarize_golden_coverage(())
    assert (result.total, result.supported, result.pending) == (0, 0, 0)


def test_domains_have_balanced_coverage():
    assert sum(c.domain == "adventureworks" for c in CATALOG) == 8
    assert sum(c.domain == "astra" for c in CATALOG) == 8
