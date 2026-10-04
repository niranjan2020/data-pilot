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


def test_comparison_summary_uses_returned_periods():
    summary = summarize_result(
        "compare revenue",
        _result(["period", "Revenue"], [["this month", 20.0], ["last month", 15.0]]),
        {"kind": "comparison", "x_column": "period", "y_columns": ["Revenue"]},
    )
    assert summary["text"] == "Revenue — this month: 20; last month: 15."


def test_ranking_summary_uses_first_returned_row():
    summary = summarize_result(
        "top products",
        _result(["Product", "Units Sold"], [["A", 20], ["B", 10]]),
        {"kind": "ranking", "x_column": "Product", "y_columns": ["Units Sold"]},
    )
    assert summary["text"] == "Top result: A with 20 Units Sold."


def test_empty_summary_does_not_invent_explanation():
    summary = summarize_result(
        "monthly revenue",
        _result(["Month", "Revenue"], []),
        {"kind": "empty"},
    )
    assert summary["text"] == "No rows matched this question."
