"""Deterministic, grounded summaries for executed query results."""

from __future__ import annotations

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


def summarize_result(question: str, result: QueryResult, presentation: dict[str, Any]) -> dict[str, Any]:
    """Build a concise answer only from returned rows; never infer missing facts."""
    if result.row_count == 0:
        return {
            "text": "No rows matched this question.",
            "kind": "empty",
            "grounded": True,
        }

    kind = str(presentation.get("kind") or "table")
    columns = list(result.columns)
    rows = list(result.rows)

    if kind == "scalar" and rows:
        y_columns = presentation.get("y_columns") or []
        measure = y_columns[0] if y_columns else columns[0]
        index = columns.index(measure) if measure in columns else 0
        return {"text": f"{measure}: {_display(rows[0][index])}.", "kind": kind, "grounded": True}

    if kind == "comparison":
        x_column = presentation.get("x_column")
        y_columns = presentation.get("y_columns") or []
        if x_column in columns and y_columns and y_columns[0] in columns:
            xi, yi = columns.index(x_column), columns.index(y_columns[0])
            parts = [f"{_display(row[xi])}: {_display(row[yi])}" for row in rows[:4]]
            return {
                "text": f"{y_columns[0]} — " + "; ".join(parts) + ".",
                "kind": kind,
                "grounded": True,
            }

    if kind == "ranking":
        x_column = presentation.get("x_column")
        y_columns = presentation.get("y_columns") or []
        if x_column in columns and y_columns and y_columns[0] in columns and rows:
            xi, yi = columns.index(x_column), columns.index(y_columns[0])
            return {
                "text": f"Top result: {_display(rows[0][xi])} with {_display(rows[0][yi])} {y_columns[0]}.",
                "kind": kind,
                "grounded": True,
            }

    if kind == "trend":
        x_column = presentation.get("x_column")
        y_columns = presentation.get("y_columns") or []
        if x_column in columns and y_columns and y_columns[0] in columns and rows:
            xi, yi = columns.index(x_column), columns.index(y_columns[0])
            first, last = rows[0], rows[-1]
            return {
                "text": (
                    f"{y_columns[0]} ranges from {_display(first[yi])} at {_display(first[xi])} "
                    f"to {_display(last[yi])} at {_display(last[xi])} across {len(rows)} returned periods."
                ),
                "kind": kind,
                "grounded": True,
            }

    return {
        "text": f"Returned {result.row_count:,} row{'s' if result.row_count != 1 else ''}.",
        "kind": kind,
        "grounded": True,
    }
