import pytest
from tests.evaluation.harness import EvaluationCase, EvaluationExpectation, EvaluationResult, EvaluationSummary


def test_evaluation_summary_reports_latency_percentiles():
    summary = EvaluationSummary(results=[
        EvaluationResult(case_id="a", passed=True, duration_ms=100),
        EvaluationResult(case_id="b", passed=True, duration_ms=200),
        EvaluationResult(case_id="c", passed=True, duration_ms=300),
    ])
    assert summary.p50_ms == 200
    assert summary.p95_ms == 290


def test_evaluation_summary_ignores_missing_latency():
    summary = EvaluationSummary(results=[
        EvaluationResult(case_id="a", passed=True),
        EvaluationResult(case_id="b", passed=True, duration_ms=125),
    ])
    assert summary.p50_ms == 125
    assert summary.p95_ms == 125


def test_evaluation_accepts_required_correctness_codes():
    from datapilot.domain.query import QueryResponse, QueryTrace
    from tests.evaluation.harness import EvaluationCase, EvaluationExpectation, evaluate_query_response

    case = EvaluationCase(
        id="correctness-codes",
        question="Show revenue by product last month",
        expected=EvaluationExpectation(
            required_correctness_codes=(
                "metric_expression_alignment",
                "grouping_dimension_alignment",
                "time_filter_alignment",
            ),
            forbidden_correctness_codes=("time_filter_violation",),
        ),
    )
    response = QueryResponse(
        question=case.question,
        status="completed",
        trace=QueryTrace(
            correctness_checks=[
                {"code": "metric_expression_alignment", "status": "passed"},
                {"code": "grouping_dimension_alignment", "status": "passed"},
                {"code": "time_filter_alignment", "status": "passed"},
            ]
        ),
    )

    result = evaluate_query_response(case, response)

    assert result.passed
    assert result.failures == ()


def test_evaluation_reports_missing_and_forbidden_correctness_codes():
    from datapilot.domain.query import QueryResponse, QueryTrace
    from tests.evaluation.harness import EvaluationCase, EvaluationExpectation, evaluate_query_response

    case = EvaluationCase(
        id="incorrect-time-grain",
        question="Show monthly revenue",
        expected=EvaluationExpectation(
            required_correctness_codes=("time_grain_alignment",),
            forbidden_correctness_codes=("time_grain_violation",),
        ),
    )
    response = QueryResponse(
        question=case.question,
        status="completed",
        trace=QueryTrace(
            correctness_checks=[
                {"code": "time_grain_violation", "status": "failed"},
            ]
        ),
    )

    result = evaluate_query_response(case, response)

    assert not result.passed
    assert "missing expected correctness checks: time_grain_alignment" in result.failures
    assert "unexpected correctness checks: time_grain_violation" in result.failures


def test_evaluation_requires_trace_for_correctness_expectations():
    from datapilot.domain.query import QueryResponse
    from tests.evaluation.harness import EvaluationCase, EvaluationExpectation, evaluate_query_response

    case = EvaluationCase(
        id="missing-trace",
        question="Show revenue",
        expected=EvaluationExpectation(
            required_correctness_codes=("physical_scope_alignment",),
        ),
    )
    response = QueryResponse(question=case.question, status="completed")

    result = evaluate_query_response(case, response)

    assert not result.passed
    assert "query trace is required for correctness evaluation" in result.failures


def test_evaluation_case_can_group_follow_up_conversation():
    case = EvaluationCase(
        id="follow-up",
        question="Only red ones",
        expected=EvaluationExpectation(require_completed=True),
        conversation_id="product-revenue",
    )

    assert case.conversation_id == "product-revenue"


def test_evaluation_summary_counts_structured_failure_categories():
    summary = EvaluationSummary(results=[
        EvaluationResult(
            case_id="semantic",
            passed=False,
            failures=("missing expected entities: Customer",),
            failure_categories=("semantic_resolution",),
        ),
        EvaluationResult(
            case_id="correctness",
            passed=False,
            failures=("unexpected correctness checks: time_grain_violation",),
            failure_categories=("governed_correctness", "time_interpretation"),
        ),
        EvaluationResult(case_id="pass", passed=True),
    ])

    assert summary.failure_category_counts["semantic_resolution"] == 1
    assert summary.failure_category_counts["governed_correctness"] == 1
    assert summary.failure_category_counts["time_interpretation"] == 1
    assert summary.failure_category_counts["execution"] == 0
    assert summary.failure_category_rates["semantic_resolution"] == pytest.approx(1 / 3)
    assert summary.category_pass_rates["semantic_resolution"] == pytest.approx(2 / 3)
    assert summary.category_pass_rates["execution"] == 1.0


def test_evaluation_summary_deduplicates_category_per_case():
    summary = EvaluationSummary(results=[
        EvaluationResult(
            case_id="multiple-correctness-failures",
            passed=False,
            failures=("failure one", "failure two"),
            failure_categories=("governed_correctness", "governed_correctness"),
        ),
    ])

    assert summary.failure_category_counts["governed_correctness"] == 1


def test_evaluation_automatically_classifies_semantic_clarification_sql_and_correctness_failures():
    from datapilot.domain.query import QueryResponse, QueryTrace
    from tests.evaluation.harness import evaluate_query_response

    case = EvaluationCase(
        id="classified-failures",
        question="Show monthly revenue",
        expected=EvaluationExpectation(
            entities=("Order",),
            clarification_kind="entity",
            require_sql=True,
            required_correctness_codes=("time_grain_alignment",),
        ),
    )
    response = QueryResponse(
        question=case.question,
        status="completed",
        trace=QueryTrace(
            governed_entities=[],
            correctness_checks=[],
        ),
    )

    result = evaluate_query_response(case, response)

    assert not result.passed
    assert set(result.failure_categories) == {
        "semantic_resolution",
        "ambiguity_clarification",
        "sql_generation",
        "governed_correctness",
    }


def test_evaluation_automatically_classifies_result_correctness_failures():
    from datapilot.domain.query import QueryResponse
    from tests.evaluation.harness import evaluate_query_response

    case = EvaluationCase(
        id="wrong-result",
        question="How many orders?",
        expected=EvaluationExpectation(row_count=2),
    )
    response = QueryResponse(
        question=case.question,
        status="completed",
        result={"rows": [[1]], "affected_tables": []},
    )

    result = evaluate_query_response(case, response)

    assert not result.passed
    assert result.failure_categories == ("result_correctness",)


def test_runtime_exception_classification_distinguishes_pipeline_stages():
    from datapilot.core.exceptions import (
        DatabaseExecutionError,
        LLMError,
        MetadataError,
        SemanticRetrievalError,
        SQLGenerationError,
        SQLValidationError,
        TimeInterpretationError,
    )
    from tests.evaluation.run_semantic import classify_runtime_exception

    assert classify_runtime_exception(SemanticRetrievalError("retrieval failed")) == ("semantic_retrieval",)
    assert classify_runtime_exception(TimeInterpretationError("time failed")) == ("time_interpretation",)
    assert classify_runtime_exception(DatabaseExecutionError("db failed")) == ("execution",)
    assert classify_runtime_exception(SQLGenerationError("generation failed")) == ("sql_generation",)
    assert classify_runtime_exception(LLMError("llm failed")) == ("sql_generation",)
    assert classify_runtime_exception(MetadataError("metadata failed")) == ("semantic_resolution",)
    assert classify_runtime_exception(SQLValidationError("unsafe sql")) == ("validation",)
    assert classify_runtime_exception(
        SQLValidationError(
            "correctness failed",
            details={"checks": [{"code": "time_grain_violation", "status": "failed"}]},
        )
    ) == ("governed_correctness",)
    assert classify_runtime_exception(RuntimeError("unknown")) == ()


def test_semantic_case_loader_preserves_rejection_expectations(tmp_path):
    import json
    from tests.evaluation.run_semantic import load_cases

    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps([{
            "id": "unsupported",
            "question": "Tell me a joke",
            "source_name": "demo",
            "expected": {
                "expected_status": "rejected",
                "rejection_code": "unsupported_question",
                "require_no_sql": True,
            },
        }]),
        encoding="utf-8",
    )

    cases = load_cases(path)

    case, source_name = cases[0]
    assert source_name == "demo"
    assert case.expected.expected_status == "rejected"
    assert case.expected.rejection_code == "unsupported_question"
    assert case.expected.require_no_sql is True


def test_semantic_case_loader_preserves_regression_provenance_and_reproduction(tmp_path):
    import json
    from tests.evaluation.run_semantic import load_cases

    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps([{
            "id": "real-usage-regression",
            "question": "Show revenue by region",
            "source_name": "demo",
            "provenance": {
                "origin": "oss_issue",
                "reference": "issue-123",
                "discovered_version": "0.1.0",
                "promoted_reason": "Wrong grouping survived generation.",
            },
            "reproduction": {
                "dialect": "postgresql",
                "provider": "postgresql",
                "fixture": "tests/fixtures/postgresql",
                "notes": "Reproduces with the generic fixture.",
            },
            "expected": {"require_completed": True},
        }]),
        encoding="utf-8",
    )

    cases = load_cases(path)

    case, _ = cases[0]
    assert case.provenance.origin == "oss_issue"
    assert case.provenance.reference == "issue-123"
    assert case.provenance.discovered_version == "0.1.0"
    assert case.provenance.promoted_reason == "Wrong grouping survived generation."
    assert case.reproduction.dialect == "postgresql"
    assert case.reproduction.provider == "postgresql"
    assert case.reproduction.fixture == "tests/fixtures/postgresql"
    assert case.reproduction.notes == "Reproduces with the generic fixture."


def test_existing_cases_receive_safe_regression_metadata_defaults():
    case = EvaluationCase(
        id="curated",
        question="Show records",
        expected=EvaluationExpectation(require_completed=True),
    )

    assert case.provenance.origin == "curated"
    assert case.provenance.reference is None
    assert case.reproduction.dialect is None
    assert case.reproduction.fixture is None


def test_regression_metadata_is_evaluator_only_and_does_not_change_expectations():
    from tests.evaluation.harness import RegressionProvenance, RegressionReproduction

    expected = EvaluationExpectation(require_completed=True, require_sql=True)
    case = EvaluationCase(
        id="metadata-only",
        question="Show records",
        expected=expected,
        provenance=RegressionProvenance(
            origin="oss_issue",
            reference="issue-42",
            promoted_reason="Preserve a reproduced failure.",
        ),
        reproduction=RegressionReproduction(
            dialect="postgresql",
            provider="postgresql",
            fixture="generic",
        ),
    )

    assert case.expected is expected
    assert not hasattr(case.expected, "provenance")
    assert not hasattr(case.expected, "reproduction")
