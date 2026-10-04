"""Deterministic, grounded summaries for executed query results."""

from __future__ import annotations

from numbers import Number
from typing import Any

from datapilot.domain.models import QueryResult


def _display(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def _number(value: Any) -> float | None:
    if isinstance(value, Number) and not isinstance(value, bool):
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


def summarize_result(question: str, result: QueryResult, presentation: dict[str, Any]) -> dict[str, Any]:
    """Build a concise analytical answer only from returned rows; never infer missing facts."""
    if result.row_count == 0:
        return {
            "text": "No rows matched this question.",
            "kind": "empty",
            "grounded": True,
            "insights": [],
        }

    kind = str(presentation.get("kind") or "table")
    columns = list(result.columns)
    rows = list(result.rows)

    if kind == "scalar" and rows:
        y_columns = presentation.get("y_columns") or []
        measure = y_columns[0] if y_columns else columns[0]
        index = columns.index(measure) if measure in columns else 0
        return {
            "text": f"{measure}: {_display(rows[0][index])}.",
            "kind": kind,
            "grounded": True,
            "insights": [{"type": "value", "measure": measure, "value": rows[0][index]}],
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

            return {"text": text, "kind": kind, "grounded": True, "insights": insights}

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

            return {"text": text, "kind": kind, "grounded": True, "insights": insights}

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

            return {"text": text, "kind": kind, "grounded": True, "insights": insights}

    return {
        "text": f"Returned {result.row_count:,} row{'s' if result.row_count != 1 else ''}.",
        "kind": kind,
        "grounded": True,
        "insights": [],
    }
