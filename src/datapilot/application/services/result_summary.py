"""Deterministic, grounded summaries for executed query results."""

from __future__ import annotations

from decimal import Decimal
from numbers import Number
from typing import Any

from datapilot.domain.models import QueryResult


def _display(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (float, Decimal)):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def _number(value: Any) -> float | None:
    if isinstance(value, (Number, Decimal)) and not isinstance(value, bool):
        return float(value)
    return None


def _change(current: Any, previous: Any) -> dict[str, Any] | None:
    current_number = _number(current)
    previous_number = _number(previous)
    if current_number is None or previous_number is None:
        return None

    delta = current_number - previous_number
    if delta > 0:
        direction = "increased"
    elif delta < 0:
        direction = "decreased"
    else:
        direction = "unchanged"

    percent = None if previous_number == 0 else (delta / abs(previous_number)) * 100
    return {"delta": delta, "percent": percent, "direction": direction}


def _diagnostics(columns: list[str], rows: list[Any], presentation: dict[str, Any]) -> list[dict[str, Any]]:
    """Detect result-quality conditions from returned data without guessing their cause."""
    if not rows:
        return [{
            "code": "empty_result",
            "severity": "info",
            "message": "The query executed successfully but returned no rows. Review filters or time range if data was expected.",
        }]

    diagnostics: list[dict[str, Any]] = []
    y_columns = [column for column in (presentation.get("y_columns") or []) if column in columns]
    for column in y_columns:
        index = columns.index(column)
        values = [row[index] for row in rows]
        if values and all(value is None for value in values):
            diagnostics.append({
                "code": "all_null_measure",
                "severity": "warning",
                "column": column,
                "message": f"{column} is NULL for every returned row. No analytical change or ranking can be calculated from this measure.",
            })
        elif any(value is None for value in values):
            diagnostics.append({
                "code": "partial_null_measure",
                "severity": "info",
                "column": column,
                "message": f"{column} contains NULL values in some returned rows.",
            })
    return diagnostics



def assess_result_quality(
    result: QueryResult,
    presentation: dict[str, Any],
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify whether an executed result is analytically usable.

    SQL execution success is intentionally separate from analytical quality.
    This assessment is deterministic and based only on returned rows plus the
    selected presentation measures.
    """
    diagnostics = diagnostics if diagnostics is not None else _diagnostics(
        list(result.columns), list(result.rows), presentation
    )
    codes = {str(item.get("code") or "") for item in diagnostics}

    if result.row_count == 0:
        return {
            "status": "empty",
            "usable": False,
            "complete": False,
            "reason": "The query executed successfully but returned no rows.",
        }
    if "all_null_measure" in codes:
        return {
            "status": "unusable",
            "usable": False,
            "complete": False,
            "reason": "At least one analytical measure is NULL for every returned row.",
        }
    if "partial_null_measure" in codes:
        return {
            "status": "partial",
            "usable": True,
            "complete": False,
            "reason": "The result is usable, but at least one analytical measure contains missing values.",
        }
    return {
        "status": "good",
        "usable": True,
        "complete": True,
        "reason": "The returned analytical measures contain usable values.",
    }



def _numeric_points(
    columns: list[str], rows: list[Any], x_column: str | None, measure: str | None
) -> list[tuple[Any, float]]:
    if x_column not in columns or measure not in columns:
        return []
    xi, yi = columns.index(x_column), columns.index(measure)
    points: list[tuple[Any, float]] = []
    for row in rows:
        value = _number(row[yi])
        if value is not None:
            points.append((row[xi], value))
    return points


def _distribution_insights(
    columns: list[str], rows: list[Any], x_column: str | None, measure: str | None
) -> list[dict[str, Any]]:
    """Calculate deterministic extrema/share insights from returned rows only."""
    points = _numeric_points(columns, rows, x_column, measure)
    if not points or measure is None:
        return []

    maximum = max(points, key=lambda item: item[1])
    minimum = min(points, key=lambda item: item[1])
    insights: list[dict[str, Any]] = [
        {"type": "maximum", "label": maximum[0], "measure": measure, "value": maximum[1]},
        {"type": "minimum", "label": minimum[0], "measure": measure, "value": minimum[1]},
    ]
    total = sum(value for _, value in points)
    if total > 0 and maximum[1] >= 0:
        insights.append({
            "type": "leader_share",
            "label": maximum[0],
            "measure": measure,
            "value": maximum[1],
            "share_percent": (maximum[1] / total) * 100,
            "returned_total": total,
        })
    return insights


def _concentration_insights(
    columns: list[str], rows: list[Any], x_column: str | None, measure: str | None
) -> list[dict[str, Any]]:
    """Describe returned-result concentration without extrapolating beyond returned rows."""
    points = _numeric_points(columns, rows, x_column, measure)
    positive = [(label, value) for label, value in points if value >= 0]
    total = sum(value for _, value in positive)
    if len(positive) < 2 or total <= 0 or measure is None:
        return []

    ordered = sorted(positive, key=lambda item: item[1], reverse=True)
    top_n = min(3, len(ordered))
    top_total = sum(value for _, value in ordered[:top_n])
    return [{
        "type": "top_n_share",
        "measure": measure,
        "n": top_n,
        "share_percent": (top_total / total) * 100,
        "returned_total": total,
        "scope": "returned_rows",
    }]



def _outlier_insights(
    columns: list[str], rows: list[Any], x_column: str | None, measure: str | None
) -> list[dict[str, Any]]:
    """Flag strong returned-row outliers using the robust IQR rule."""
    points = _numeric_points(columns, rows, x_column, measure)
    if len(points) < 4 or measure is None:
        return []

    ordered_values = sorted(value for _, value in points)

    def median(values: list[float]) -> float:
        size = len(values)
        middle = size // 2
        if size % 2:
            return values[middle]
        return (values[middle - 1] + values[middle]) / 2

    middle = len(ordered_values) // 2
    # Tukey hinges: for an odd-sized sample include the overall median in
    # both halves. This keeps small returned result sets from allowing one
    # extreme value to inflate Q3 and hide itself as an outlier.
    if len(ordered_values) % 2:
        lower = ordered_values[: middle + 1]
        upper = ordered_values[middle:]
    else:
        lower = ordered_values[:middle]
        upper = ordered_values[middle:]
    q1, q3 = median(lower), median(upper)
    iqr = q3 - q1
    if iqr <= 0:
        return []

    lower_bound, upper_bound = q1 - (1.5 * iqr), q3 + (1.5 * iqr)
    outliers = [
        (label, value)
        for label, value in points
        if value < lower_bound or value > upper_bound
    ]
    return [
        {
            "type": "outlier",
            "label": label,
            "measure": measure,
            "value": value,
            "direction": "high" if value > upper_bound else "low",
            "method": "iqr_1_5",
            "scope": "returned_rows",
        }
        for label, value in outliers[:3]
    ]


def _trend_movement_insights(
    columns: list[str], rows: list[Any], x_column: str | None, measure: str | None
) -> list[dict[str, Any]]:
    """Summarize the strongest adjacent movements in the returned time series."""
    points = _numeric_points(columns, rows, x_column, measure)
    if len(points) < 2 or measure is None:
        return []

    movements: list[dict[str, Any]] = []
    for index in range(1, len(points)):
        previous_label, previous_value = points[index - 1]
        label, value = points[index]
        change = _change(value, previous_value)
        if change is None:
            continue
        movements.append({
            "from_label": previous_label,
            "to_label": label,
            "from_value": previous_value,
            "to_value": value,
            **change,
        })

    if not movements:
        return []

    largest = max(movements, key=lambda item: abs(item["delta"]))
    insights: list[dict[str, Any]] = [{
        "type": "largest_period_change",
        "measure": measure,
        "scope": "returned_periods",
        **largest,
    }]

    increases = [item for item in movements if item["delta"] > 0]
    decreases = [item for item in movements if item["delta"] < 0]
    if increases:
        strongest_increase = max(increases, key=lambda item: item["delta"])
        insights.append({
            "type": "strongest_period_increase",
            "measure": measure,
            "scope": "returned_periods",
            **strongest_increase,
        })
    if decreases:
        strongest_decrease = min(decreases, key=lambda item: item["delta"])
        insights.append({
            "type": "strongest_period_decrease",
            "measure": measure,
            "scope": "returned_periods",
            **strongest_decrease,
        })
    return insights

def summarize_result(question: str, result: QueryResult, presentation: dict[str, Any]) -> dict[str, Any]:
    """Build a concise analytical answer only from returned rows; never infer missing facts."""
    kind = str(presentation.get("kind") or "table")
    columns = list(result.columns)
    rows = list(result.rows)
    diagnostics = _diagnostics(columns, rows, presentation)
    quality = assess_result_quality(result, presentation, diagnostics)

    if result.row_count == 0:
        return {
            "text": "No rows matched this question.",
            "kind": "empty",
            "grounded": True,
            "insights": [],
            "diagnostics": diagnostics,
            "quality": quality,
        }

    if kind == "scalar" and rows:
        y_columns = presentation.get("y_columns") or []
        measure = y_columns[0] if y_columns else columns[0]
        index = columns.index(measure) if measure in columns else 0
        return {
            "text": f"{measure}: {_display(rows[0][index])}.",
            "kind": kind,
            "grounded": True,
            "insights": [{"type": "value", "measure": measure, "value": rows[0][index]}],
            "diagnostics": diagnostics,
            "quality": quality,
        }

    if kind == "comparison":
        x_column = presentation.get("x_column")
        y_columns = presentation.get("y_columns") or []
        if x_column in columns and y_columns and y_columns[0] in columns:
            measure = y_columns[0]
            xi, yi = columns.index(x_column), columns.index(measure)
            parts = [f"{_display(row[xi])}: {_display(row[yi])}" for row in rows[:4]]
            insights: list[dict[str, Any]] = []
            text = f"{measure} — " + "; ".join(parts) + "."

            if len(rows) >= 2:
                change = _change(rows[0][yi], rows[1][yi])
                if change is not None:
                    insight = {
                        "type": "period_change",
                        "measure": measure,
                        "current_label": rows[0][xi],
                        "previous_label": rows[1][xi],
                        **change,
                    }
                    insights.append(insight)
                    if change["direction"] == "unchanged":
                        text += f" {measure} was unchanged versus {_display(rows[1][xi])}."
                    elif change["percent"] is None:
                        text += (
                            f" {measure} {change['direction']} by {_display(abs(change['delta']))} "
                            f"versus {_display(rows[1][xi])}; percentage change is unavailable because the prior value is zero."
                        )
                    else:
                        text += (
                            f" {measure} {change['direction']} by {_display(abs(change['delta']))} "
                            f"({abs(change['percent']):.1f}%) versus {_display(rows[1][xi])}."
                        )

            return {"text": text, "kind": kind, "grounded": True, "insights": insights, "diagnostics": diagnostics, "quality": quality}

    if kind == "ranking":
        x_column = presentation.get("x_column")
        y_columns = presentation.get("y_columns") or []
        if x_column in columns and y_columns and y_columns[0] in columns and rows:
            measure = y_columns[0]
            xi, yi = columns.index(x_column), columns.index(measure)
            text = f"Top result: {_display(rows[0][xi])} with {_display(rows[0][yi])} {measure}."
            insights = [{"type": "leader", "label": rows[0][xi], "measure": measure, "value": rows[0][yi]}]

            if len(rows) >= 2:
                leader = _number(rows[0][yi])
                runner_up = _number(rows[1][yi])
                if leader is not None and runner_up is not None:
                    gap = leader - runner_up
                    text += f" It leads {_display(rows[1][xi])} by {_display(abs(gap))}."
                    insights.append(
                        {"type": "leader_gap", "runner_up": rows[1][xi], "measure": measure, "delta": gap}
                    )

            insights.extend(_distribution_insights(columns, rows, x_column, measure))
            insights.extend(_concentration_insights(columns, rows, x_column, measure))
            insights.extend(_outlier_insights(columns, rows, x_column, measure))
            return {"text": text, "kind": kind, "grounded": True, "insights": insights, "diagnostics": diagnostics, "quality": quality}

    if kind == "trend":
        x_column = presentation.get("x_column")
        y_columns = presentation.get("y_columns") or []
        if x_column in columns and y_columns and y_columns[0] in columns and rows:
            measure = y_columns[0]
            xi, yi = columns.index(x_column), columns.index(measure)
            first, last = rows[0], rows[-1]
            text = (
                f"{measure} ranges from {_display(first[yi])} at {_display(first[xi])} "
                f"to {_display(last[yi])} at {_display(last[xi])} across {len(rows)} returned periods."
            )
            insights: list[dict[str, Any]] = []
            change = _change(last[yi], first[yi])
            if change is not None and len(rows) > 1:
                insights.append(
                    {
                        "type": "trend_change",
                        "measure": measure,
                        "first_label": first[xi],
                        "last_label": last[xi],
                        **change,
                    }
                )
                if change["direction"] == "unchanged":
                    text += " The first and last returned values are unchanged."
                elif change["percent"] is None:
                    text += (
                        f" From the first to last returned period it {change['direction']} "
                        f"by {_display(abs(change['delta']))}; percentage change is unavailable because the first value is zero."
                    )
                else:
                    text += (
                        f" From the first to last returned period it {change['direction']} "
                        f"by {_display(abs(change['delta']))} ({abs(change['percent']):.1f}%)."
                    )

            distribution = _distribution_insights(columns, rows, x_column, measure)
            insights.extend(distribution)
            points = _numeric_points(columns, rows, x_column, measure)
            if len(points) >= 3:
                deltas = [points[index][1] - points[index - 1][1] for index in range(1, len(points))]
                direction = (
                    "increasing" if all(delta > 0 for delta in deltas)
                    else "decreasing" if all(delta < 0 for delta in deltas)
                    else "flat" if all(delta == 0 for delta in deltas)
                    else "mixed"
                )
                insights.append({"type": "trend_pattern", "measure": measure, "direction": direction})
            insights.extend(_trend_movement_insights(columns, rows, x_column, measure))
            return {"text": text, "kind": kind, "grounded": True, "insights": insights, "diagnostics": diagnostics, "quality": quality}

    return {
        "text": f"Returned {result.row_count:,} row{'s' if result.row_count != 1 else ''}.",
        "kind": kind,
        "grounded": True,
        "insights": [],
        "diagnostics": diagnostics,
        "quality": quality,
    }
