from decimal import Decimal

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


def test_postgresql_decimal_measure_is_ranked_not_plain_table():
    plan = plan_result_presentation(
        "show top 10 products by revenue",
        _result(
            ["Name", "revenue"],
            [["Mountain-200 Black, 38", Decimal("4400992.80040000")],
             ["Mountain-200 Black, 42", Decimal("4009494.76184100")]],
        ),
    )
    assert plan["kind"] == "ranking"
    assert plan["recommended_visual"] == "bar"
    assert plan["x_column"] == "Name"
    assert plan["y_columns"] == ["revenue"]


def test_detail_records_with_year_and_numeric_id_remain_table():
    result = _result(
        ["id", "imo", "vessel_name", "ordered_year", "ordered_month"],
        [[11257, 9000001, "A", 2026, 2], [11258, 9000002, "B", 2026, 2]],
    )
    plan = plan_result_presentation("List all orders placed in the last 6 months", result)
    assert plan["kind"] == "table"
    assert plan["recommended_visual"] == "table"


def test_detail_records_with_numeric_measure_remain_table():
    result = _result(
        ["id", "vessel_name", "built_year", "capacity"],
        [[1, "A", 2000, 12000], [2, "B", 2002, 13000]],
    )
    assert plan_result_presentation("show vessels older than 20 years", result)["kind"] == "table"


def test_repeated_temporal_buckets_do_not_form_trend():
    result = _result(
        ["order_date", "revenue"],
        [["2026-01-01", 10], ["2026-01-01", 20]],
    )
    assert plan_result_presentation("show revenue", result)["kind"] != "trend"


def test_aggregated_numeric_year_remains_a_trend():
    result = _result(["year", "revenue"], [[2024, 10], [2025, 20]])
    assert plan_result_presentation("revenue by year", result)["kind"] == "trend"
