from tests.evaluation.harness import EvaluationResult, EvaluationSummary


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
