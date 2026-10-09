"""Fail-closed parameterized filters over explicitly approved dimensions.

This builds a safe predicate fragment, not a standalone executable query.
The caller must validate source compatibility, policy, and operation order
before composing it into a SQL statement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datapilot.application.services.analytical_dimensions import (
    AnalyticalDimension,
    resolve_analytical_dimension,
)


@dataclass(frozen=True)
class CompiledAnalyticalFilter:
    sql: str
    parameters: tuple[Any, ...]
    entity_id: int
    schema_name: str
    table_name: str


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Invalid governed filter identifier")
    return '"' + value.replace('"', '""') + '"'


def compile_governed_dimension_filter(
    *,
    dimension_name: str,
    operator: str,
    values: tuple[Any, ...],
    published_dimensions: tuple[AnalyticalDimension, ...],
    max_values: int = 100,
) -> CompiledAnalyticalFilter:
    """Compile EQ or IN using only published physical columns and bind values.

    Category labels must be resolved to governed database values upstream.
    This function deliberately does not guess label-to-value mappings.
    """
    if type(max_values) is not int or max_values < 1:
        raise ValueError("Invalid filter value limit")
    if not isinstance(dimension_name, str) or not dimension_name.strip():
        raise ValueError("A governed filter dimension is required")
    if type(operator) is not str or operator not in ("EQ", "IN"):
        raise ValueError("Unsupported governed filter operator")
    if not isinstance(values, tuple) or not 1 <= len(values) <= max_values:
        raise ValueError("Filter requires bounded parameter values")
    if operator == "EQ" and len(values) != 1:
        raise ValueError("EQ requires exactly one value")
    for value in values:
        if type(value) not in (str, int, float, bool):
            raise ValueError("Unsupported filter value type")
        if isinstance(value, str) and len(value) > 4096:
            raise ValueError("Filter value exceeds size limit")
        if isinstance(value, float):
            import math
            if not math.isfinite(value):
                raise ValueError("Non-finite filter values are forbidden")
    dimension = resolve_analytical_dimension(published_dimensions, dimension_name)
    column = _identifier(dimension.column_name)
    _identifier(dimension.schema_name)
    _identifier(dimension.table_name)
    placeholders = ", ".join(["%s"] * len(values))
    sql = f"{column} = %s" if operator == "EQ" else f"{column} IN ({placeholders})"
    return CompiledAnalyticalFilter(
        sql=sql, parameters=values, entity_id=dimension.entity_id,
        schema_name=dimension.schema_name, table_name=dimension.table_name,
    )
