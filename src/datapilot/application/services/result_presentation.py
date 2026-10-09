"""Deterministic presentation planning for executed query results."""

from __future__ import annotations

from decimal import Decimal
from numbers import Number
import re
from typing import Any

from datapilot.domain.models import QueryResult


_TIME_HINTS = ("date", "time", "month", "quarter", "year", "week", "day", "period")
_RANK_HINTS = ("top ", "bottom ", "highest", "lowest", "rank")
_COMPARE_HINTS = ("compare", " vs ", " versus ")


def _identifier_column(name: str) -> bool:
    """Identifiers are dimensions even when stored as numbers."""
    parts = re.sub(r"([a-z])([A-Z])", r"\1_\2", name).lower()
    return bool(re.search(r"(^|_)(id|ids|imo|uuid|guid|key|code|number|no)($|_)", parts)) or parts.endswith("_id")


def _temporal_column(name: str) -> bool:
    """Match time roles on word boundaries, not arbitrary substrings."""
    parts = re.sub(r"([a-z])([A-Z])", r"\1_\2", name).lower()
    return any(part in _TIME_HINTS for part in re.split(r"[^a-z]+", parts) if part)


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
        if values and all(isinstance(value, (Number, Decimal)) and not isinstance(value, bool) for value in values):
            numeric_indices.append(index)

    # An ID, calendar year, or month number is not an analytical measure.
    numeric_indices = [i for i in numeric_indices if not _identifier_column(columns[i]) and not _temporal_column(columns[i])]
    numeric_columns = [columns[i] for i in numeric_indices]
    dimension_columns = [c for i, c in enumerate(columns) if i not in numeric_indices]

    # Detail listings can contain multiple numeric fields (IDs, quantities, dates).
    # Without an actual measure, never invent trends, ranking, or KPI cards.
    if not numeric_columns:
        plan["reason"] = "Individual records are best presented in a table; no aggregated measure was returned."
        return plan

    # A row-level identifier alongside descriptive columns signals a listing,
    # even if another numeric column (price, capacity, age) is present.
    if any(_identifier_column(c) for c in columns) and len(columns) > 2 and result.row_count > 1:
        plan["reason"] = "The result contains individual records; use the raw table instead of a derived trend."
        return plan

    if result.row_count == 1 and len(numeric_columns) == 1:
        plan.update(kind="scalar", recommended_visual="kpi", y_columns=numeric_columns,
                    reason="A single row with one numeric measure is best presented as a KPI.")
        return plan

    # A synthetic period label represents discrete comparison buckets, not a
    # chronological series. Check it before generic time-name detection because
    # "period_label" intentionally contains the word "period".
    period_column = next((c for c in columns if c.lower() in {"period", "period_label"}), None)
    if period_column and numeric_columns:
        plan.update(kind="comparison", recommended_visual="bar", x_column=period_column,
                    y_columns=numeric_columns,
                    reason="Named comparison periods with numeric measures are best compared with bars.")
        return plan

    temporal_column = next((c for c in columns if _temporal_column(c)), None)
    grouping_grain = time_interpretation.get("grouping_grain")
    # A genuine series needs one point per time bucket. Repeated dates/years
    # indicate detail records, not an ordered aggregate trend.
    distinct_periods = bool(temporal_column) and len({str(row[columns.index(temporal_column)]) for row in result.rows}) == len(result.rows)
    if temporal_column and numeric_columns and distinct_periods and (grouping_grain or result.row_count > 1):
        plan.update(kind="trend", recommended_visual="line", x_column=temporal_column,
                    y_columns=numeric_columns,
                    reason="An ordered time dimension with numeric measures is best presented as a trend.")
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
