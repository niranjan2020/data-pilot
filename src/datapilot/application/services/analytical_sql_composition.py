"""Internal typed SQL clause assembly for already governed physical bindings.

Fragments in this module are compiler-owned SQL, never user request text.
No execution or authorization is performed. Callers must validate semantic
bindings and source compatibility before constructing clause objects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BoundPredicate:
    sql: str
    parameters: tuple[Any, ...]


@dataclass(frozen=True)
class GroupedQueryClauses:
    select: tuple[str, ...]
    source: str
    group_by: tuple[str, ...]
    where: tuple[BoundPredicate, ...] = ()
    having: tuple[BoundPredicate, ...] = ()
    order_by: tuple[str, ...] = ()
    limit: int | None = None
    parenthesize_predicates: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.select, tuple) or not self.select:
            raise ValueError("SELECT expressions are required")
        if not isinstance(self.group_by, tuple) or not self.group_by:
            raise ValueError("GROUP BY expressions are required")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("A governed FROM source is required")
        for fragments in (self.select, self.group_by, self.order_by):
            if not isinstance(fragments, tuple) or any(
                not isinstance(fragment, str) or not fragment.strip()
                for fragment in fragments
            ):
                raise ValueError("Invalid compiler-owned SQL fragments")
        for predicates in (self.where, self.having):
            if not isinstance(predicates, tuple) or any(
                not isinstance(predicate, BoundPredicate)
                or not isinstance(predicate.sql, str)
                or not predicate.sql.strip()
                or not isinstance(predicate.parameters, tuple)
                for predicate in predicates
            ):
                raise ValueError("Invalid bound SQL predicate")
        if type(self.parenthesize_predicates) is not bool:
            raise ValueError("Invalid predicate formatting option")
        if self.limit is not None and (
            type(self.limit) is not int or self.limit < 1
        ):
            raise ValueError("LIMIT requires a positive integer")


@dataclass(frozen=True)
class ComposedGroupedQuery:
    sql: str
    parameters: tuple[Any, ...]


def compose_grouped_query(clauses: GroupedQueryClauses) -> ComposedGroupedQuery:
    """Render canonical SQL clause order, preserving DB parameter order."""
    if not isinstance(clauses, GroupedQueryClauses):
        raise ValueError("Governed grouped query clauses are required")
    sql = "SELECT " + ", ".join(clauses.select) + " FROM " + clauses.source
    parameters: list[Any] = []
    if clauses.where:
        sql += " WHERE " + " AND ".join(
            "(" + predicate.sql + ")" if clauses.parenthesize_predicates else predicate.sql
            for predicate in clauses.where
        )
        for predicate in clauses.where:
            parameters.extend(predicate.parameters)
    sql += " GROUP BY " + ", ".join(clauses.group_by)
    if clauses.having:
        sql += " HAVING " + " AND ".join(
            "(" + predicate.sql + ")" if clauses.parenthesize_predicates else predicate.sql
            for predicate in clauses.having
        )
        for predicate in clauses.having:
            parameters.extend(predicate.parameters)
    if clauses.order_by:
        sql += " ORDER BY " + ", ".join(clauses.order_by)
    if clauses.limit is not None:
        sql += f" LIMIT {clauses.limit}"
    return ComposedGroupedQuery(sql=sql, parameters=tuple(parameters))
