from datapilot.application.services.result_summary import summarize_result
from datapilot.domain.models import QueryResult


def _result(columns, rows):
    return QueryResult(columns=columns, rows=rows, row_count=len(rows), execution_time_ms=1)


def test_scalar_summary_is_grounded():
    summary = summarize_result(
        "show order count",
        _result(["Order Count"], [[31465]]),
        {"kind": "scalar", "y_columns": ["Order Count"]},
    )
    assert summary["text"] == "Order Count: 31,465."
    assert summary["grounded"] is True
    assert summary["insights"][0]["value"] == 31465


def test_comparison_summary_calculates_delta_and_percent():
    summary = summarize_result(
        "compare revenue",
        _result(["period", "Revenue"], [["this month", 20.0], ["last month", 15.0]]),
        {"kind": "comparison", "x_column": "period", "y_columns": ["Revenue"]},
    )
    assert summary["text"] == (
        "Revenue — this month: 20; last month: 15. "
        "Revenue increased by 5 (33.3%) versus last month."
    )
    assert summary["insights"][0]["delta"] == 5.0
    assert round(summary["insights"][0]["percent"], 1) == 33.3
    assert summary["insights"][0]["direction"] == "increased"


def test_comparison_with_zero_baseline_does_not_invent_percent():
    summary = summarize_result(
        "compare revenue",
        _result(["period", "Revenue"], [["this month", 20.0], ["last month", 0.0]]),
        {"kind": "comparison", "x_column": "period", "y_columns": ["Revenue"]},
    )
    assert summary["insights"][0]["percent"] is None
    assert "percentage change is unavailable" in summary["text"]


def test_ranking_summary_adds_runner_up_gap():
    summary = summarize_result(
        "top products",
        _result(["Product", "Units Sold"], [["A", 20], ["B", 10]]),
        {"kind": "ranking", "x_column": "Product", "y_columns": ["Units Sold"]},
    )
    assert summary["text"] == "Top result: A with 20 Units Sold. It leads B by 10."
    assert summary["insights"][1]["delta"] == 10.0


def test_trend_summary_calculates_first_to_last_change():
    summary = summarize_result(
        "monthly revenue",
        _result(["Month", "Revenue"], [["Jan", 100.0], ["Feb", 120.0], ["Mar", 150.0]]),
        {"kind": "trend", "x_column": "Month", "y_columns": ["Revenue"]},
    )
    assert "increased by 50 (50.0%)" in summary["text"]
    assert summary["insights"][0]["direction"] == "increased"
    assert summary["insights"][0]["delta"] == 50.0


def test_decrease_is_reported_with_positive_magnitude():
    summary = summarize_result(
        "compare revenue",
        _result(["period", "Revenue"], [["this month", 75.0], ["last month", 100.0]]),
        {"kind": "comparison", "x_column": "period", "y_columns": ["Revenue"]},
    )
    assert "decreased by 25 (25.0%)" in summary["text"]
    assert summary["insights"][0]["delta"] == -25.0


def test_empty_summary_does_not_invent_explanation():
    summary = summarize_result(
        "monthly revenue",
        _result(["Month", "Revenue"], []),
        {"kind": "empty"},
    )
    assert summary["text"] == "No rows matched this question."
    assert summary["insights"] == []


def test_all_null_measure_is_reported_without_guessing_cause():
    summary = summarize_result(
        "compare revenue",
        _result(["period", "Revenue"], [["this month", None], ["last month", None]]),
        {"kind": "comparison", "x_column": "period", "y_columns": ["Revenue"]},
    )
    assert summary["diagnostics"][0]["code"] == "all_null_measure"
    assert summary["diagnostics"][0]["severity"] == "warning"
    assert "NULL for every returned row" in summary["diagnostics"][0]["message"]


def test_partial_null_measure_is_reported():
    summary = summarize_result(
        "monthly revenue",
        _result(["Month", "Revenue"], [["Jan", 10.0], ["Feb", None]]),
        {"kind": "trend", "x_column": "Month", "y_columns": ["Revenue"]},
    )
    assert summary["diagnostics"][0]["code"] == "partial_null_measure"


def test_empty_result_includes_non_speculative_diagnostic():
    summary = summarize_result(
        "revenue this month",
        _result(["Revenue"], []),
        {"kind": "empty", "y_columns": ["Revenue"]},
    )
    assert summary["diagnostics"][0]["code"] == "empty_result"
    assert "Review filters or time range" in summary["diagnostics"][0]["message"]



def test_result_quality_good_when_measure_values_are_complete():
    summary = summarize_result(
        "monthly revenue",
        _result(["Month", "Revenue"], [["Jan", 10.0], ["Feb", 12.0]]),
        {"kind": "trend", "x_column": "Month", "y_columns": ["Revenue"]},
    )
    assert summary["quality"]["status"] == "good"
    assert summary["quality"]["usable"] is True
    assert summary["quality"]["complete"] is True


def test_result_quality_partial_when_measure_has_missing_values():
    summary = summarize_result(
        "monthly revenue",
        _result(["Month", "Revenue"], [["Jan", 10.0], ["Feb", None]]),
        {"kind": "trend", "x_column": "Month", "y_columns": ["Revenue"]},
    )
    assert summary["quality"]["status"] == "partial"
    assert summary["quality"]["usable"] is True
    assert summary["quality"]["complete"] is False


def test_result_quality_unusable_when_measure_is_entirely_null():
    summary = summarize_result(
        "compare revenue",
        _result(["period", "Revenue"], [["current", None], ["previous", None]]),
        {"kind": "comparison", "x_column": "period", "y_columns": ["Revenue"]},
    )
    assert summary["quality"]["status"] == "unusable"
    assert summary["quality"]["usable"] is False


def test_result_quality_empty_is_not_analytically_usable():
    summary = summarize_result(
        "revenue this month",
        _result(["Revenue"], []),
        {"kind": "empty", "y_columns": ["Revenue"]},
    )
    assert summary["quality"]["status"] == "empty"
    assert summary["quality"]["usable"] is False
