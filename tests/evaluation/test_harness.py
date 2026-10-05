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
