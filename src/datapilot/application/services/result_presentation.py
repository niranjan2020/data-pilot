"""Deterministic presentation planning for executed query results."""

from __future__ import annotations

from typing import Any

from datapilot.domain.models import QueryResult


_TIME_HINTS = ("date", "time", "month", "quarter", "year", "week", "day", "period")
_RANK_HINTS = ("top ", "bottom ", "highest", "lowest", "rank")
_COMPARE_HINTS = ("compare", " vs ", " versus ")


def plan_result_presentation(question: str, result: QueryResult, time_interpretation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify a result and recommend a presentation without another LLM call."""
    columns = list(result.columns)
    lower_columns = [c.lower() for c in columns]
    q = f" {question.lower()} "
    time_interpretation = time_interpretation or {}

    plan: dict[str, Any] = {
        "kind": "empty" if result.row_count == 0 else "table",
        "recommended_visual": "table",
        "x_column": None,
        "y_columns": [],
        "reason": "",
    }
    if result.row_count == 0:
        plan["reason"] = "The query returned no rows."
        return plan

    numeric_indices: list[int] = []
    for index in range(len(columns)):
        values = [row[index] for row in result.rows if index < len(row) and row[index] is not None]
        if values and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            numeric_indices.append(index)

    numeric_columns = [columns[i] for i in numeric_indices]
    dimension_columns = [c for i, c in enumerate(columns) if i not in numeric_indices]

    if result.row_count == 1 and len(numeric_columns) == 1:
        plan.update(kind="scalar", recommended_visual="kpi", y_columns=numeric_columns,
                    reason="A single row with one numeric measure is best presented as a KPI.")
        return plan

    temporal_column = next((c for c in columns if any(h in c.lower() for h in _TIME_HINTS)), None)
    grouping_grain = time_interpretation.get("grouping_grain")
    if temporal_column and numeric_columns and (grouping_grain or result.row_count > 1):
        plan.update(kind="trend", recommended_visual="line", x_column=temporal_column,
                    y_columns=numeric_columns,
                    reason="An ordered time dimension with numeric measures is best presented as a trend.")
        return plan

    period_column = next((c for c in columns if c.lower() in {"period", "period_label"}), None)
    if period_column and numeric_columns:
        plan.update(kind="comparison", recommended_visual="bar", x_column=period_column,
                    y_columns=numeric_columns,
                    reason="Named comparison periods with numeric measures are best compared with bars.")
        return plan

    if any(h in q for h in _COMPARE_HINTS) and dimension_columns and numeric_columns:
        plan.update(kind="comparison", recommended_visual="bar", x_column=dimension_columns[0],
                    y_columns=numeric_columns,
                    reason="The question requests a comparison across categories.")
        return plan

    if any(h in q for h in _RANK_HINTS) and dimension_columns and numeric_columns:
        plan.update(kind="ranking", recommended_visual="bar", x_column=dimension_columns[0],
                    y_columns=numeric_columns,
                    reason="A ranked categorical result is best presented as bars.")
        return plan

    if dimension_columns and numeric_columns and result.row_count <= 30:
        plan.update(kind="categorical", recommended_visual="bar", x_column=dimension_columns[0],
                    y_columns=numeric_columns,
                    reason="A compact categorical result with numeric measures is suitable for a bar chart.")
        return plan

    plan["reason"] = "The result shape is best preserved as a table."
    return plan
