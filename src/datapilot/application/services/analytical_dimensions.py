"""Derive analytical grouping dimensions from governed semantic attributes.

Entity names identify business objects; they are not automatically grouping
columns. Attribute definitions retain their owner and physical column for
future SQL compilation, without trusting arbitrary client-provided SQL.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class AnalyticalDimension:
    name: str
    entity_id: int
    entity_name: str
    schema_name: str
    table_name: str
    column_name: str


def extract_analytical_dimensions(
    entities: list[dict[str, Any]],
) -> tuple[AnalyticalDimension, ...]:
    """Extract qualified attribute dimensions; reject incomplete governance.

    Unqualified attribute names are rejected when they occur on multiple
    entities. Callers must choose a disambiguated semantic identity rather
    than silently binding the wrong physical column.
    """
    result: list[AnalyticalDimension] = []
    seen: set[tuple[int, str]] = set()
    for entity in entities:
        if not isinstance(entity, Mapping):
            raise ValueError("Invalid governed entity")
        identifier = entity.get("id")
        if type(identifier) is not int or identifier < 1:
            raise ValueError("Invalid governed entity identifier")
        owner = entity.get("name")
        schema = entity.get("schema_name")
        table = entity.get("table_name")
        attributes = entity.get("attributes", [])
        if not isinstance(attributes, list):
            raise ValueError("Invalid governed attributes")
        if not attributes:
            continue
        if not all(isinstance(x, str) and x.strip() for x in (owner, schema, table)):
            raise ValueError("Incomplete governed entity mapping")
        for attribute in attributes:
            if not isinstance(attribute, Mapping):
                raise ValueError("Invalid governed attribute")
            name = attribute.get("name")
            column = attribute.get("column_name")
            if not all(isinstance(x, str) and x.strip() for x in (name, column)):
                raise ValueError("Incomplete governed attribute mapping")
            key = (identifier, name.casefold())
            if key in seen:
                raise ValueError("Duplicate governed attribute")
            seen.add(key)
            result.append(AnalyticalDimension(
                name=name, entity_id=identifier, entity_name=owner,
                schema_name=schema, table_name=table, column_name=column,
            ))
    return tuple(result)


def resolve_analytical_dimension(
    dimensions: tuple[AnalyticalDimension, ...], name: str,
) -> AnalyticalDimension:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Analytical dimension name is required")
    requested = name.strip().casefold()
    matches = [
        dimension for dimension in dimensions
        if dimension.name.casefold() == requested
        or f"{dimension.entity_name}.{dimension.name}".casefold() == requested
    ]
    if len(matches) != 1:
        raise ValueError("Unknown or ambiguous analytical dimension")
    return matches[0]
