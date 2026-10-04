from datapilot.application.services.result_presentation import plan_result_presentation
from datapilot.domain.models import QueryResult


def _result(columns, rows):
    return QueryResult(columns=columns, rows=rows, row_count=len(rows), execution_time_ms=1)


def test_scalar_becomes_kpi():
    plan = plan_result_presentation("show order count", _result(["Order Count"], [[42]]))
    assert plan["kind"] == "scalar"
    assert plan["recommended_visual"] == "kpi"


def test_monthly_series_becomes_line():
    plan = plan_result_presentation(
        "show monthly revenue this year",
        _result(["Order Date_month", "Revenue"], [["2026-01-01", 10.0], ["2026-02-01", 12.0]]),
        {"grouping_grain": "month"},
    )
    assert plan["kind"] == "trend"
    assert plan["recommended_visual"] == "line"
    assert plan["x_column"] == "Order Date_month"


def test_period_comparison_becomes_bar():
    plan = plan_result_presentation(
        "compare revenue this month vs last month",
        _result(["period_label", "Revenue"], [["this month", 20.0], ["last month", 15.0]]),
    )
    assert plan["kind"] == "comparison"
    assert plan["recommended_visual"] == "bar"


def test_top_n_becomes_ranking():
    plan = plan_result_presentation(
        "show top 10 products by units sold",
        _result(["Product", "Units Sold"], [["A", 20], ["B", 10]]),
    )
    assert plan["kind"] == "ranking"
    assert plan["recommended_visual"] == "bar"


def test_empty_result_stays_empty():
    plan = plan_result_presentation("show monthly revenue", _result(["Month", "Revenue"], []))
    assert plan["kind"] == "empty"
    assert plan["recommended_visual"] == "table"


def test_wide_non_numeric_result_stays_table():
    plan = plan_result_presentation(
        "show products",
        _result(["Name", "Color"], [["A", "Red"], ["B", "Blue"]]),
    )
    assert plan["kind"] == "table"
    assert plan["recommended_visual"] == "table"
