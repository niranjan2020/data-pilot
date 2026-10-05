"""Deterministic correctness checks between governed context and generated SQL."""

from __future__ import annotations

from typing import Any, Iterable

from sqlglot import exp, parse_one


def _normalise(name: str) -> str:
    return str(name or "").strip().strip('"').casefold()


def _within_governed_scope(table: str, governed_tables: Iterable[str]) -> bool:
    candidate = _normalise(table)
    candidate_leaf = candidate.rsplit(".", 1)[-1]
    for governed in governed_tables:
        allowed = _normalise(governed)
        if candidate == allowed:
            return True
        # Validators may report either schema-qualified or unqualified names.
        if candidate_leaf == allowed.rsplit(".", 1)[-1]:
            return True
    return False


def _canonical_expression(expression: exp.Expression) -> str:
    """Canonicalize a row-level expression while ignoring SQL aliases/qualifiers."""
    copy = expression.copy()
    for column in copy.find_all(exp.Column):
        column.set("table", None)
        column.set("db", None)
        column.set("catalog", None)
    return copy.sql(dialect="postgres").casefold().replace(" ", "")


def _metric_expression_checks(sql: str, governed_metrics: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    derived = [
        metric for metric in governed_metrics
        if str(metric.get("calculation_expression") or "").strip()
    ]
    if not derived:
        return []

    try:
        tree = parse_one(sql, read="postgres")
    except Exception:
        return [{
            "code": "metric_expression_verification_unavailable",
            "status": "skipped",
            "severity": "info",
            "message": "Metric-expression verification could not parse the validated SQL.",
        }]

    checks: list[dict[str, Any]] = []
    aggregate_nodes = list(tree.find_all(exp.AggFunc))
    for metric in derived:
        name = str(metric.get("name") or "metric")
        expression_sql = str(metric.get("calculation_expression") or "").strip()
        aggregation = str(metric.get("aggregation") or "").strip().casefold()
        try:
            expected = _canonical_expression(parse_one(expression_sql, read="postgres"))
        except Exception:
            checks.append({
                "code": "metric_expression_verification_unavailable",
                "status": "skipped",
                "severity": "warning",
                "metric": name,
                "message": f"Governed calculation expression for {name} could not be parsed.",
            })
            continue

        matched = False
        for node in aggregate_nodes:
            if node.key.casefold() != aggregation:
                continue
            argument = node.this
            if argument is not None and _canonical_expression(argument) == expected:
                matched = True
                break

        if matched:
            checks.append({
                "code": "metric_expression_alignment",
                "status": "passed",
                "severity": "info",
                "metric": name,
                "aggregation": aggregation,
                "message": f"{name} uses its governed calculation expression and aggregation.",
            })
        else:
            checks.append({
                "code": "metric_expression_violation",
                "status": "failed",
                "severity": "error",
                "metric": name,
                "aggregation": aggregation,
                "expected_expression": expression_sql,
                "message": f"Generated SQL does not use the governed {aggregation.upper()} expression for {name}.",
            })
    return checks


def assess_query_correctness(
    *,
    affected_tables: Iterable[str],
    governed_tables: Iterable[str],
    sql: str | None = None,
    governed_metrics: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Return deterministic pre-execution alignment checks.

    This deliberately does not ask an LLM to judge its own SQL. The first
    production invariant is physical-scope containment: generated SQL may only
    touch tables selected by the governed semantic/physical context.
    """
    affected = [str(item) for item in affected_tables if str(item or "").strip()]
    governed = [str(item) for item in governed_tables if str(item or "").strip()]

    metric_checks = _metric_expression_checks(sql, governed_metrics) if sql else []

    if not governed:
        return metric_checks + [{
            "code": "governed_scope_unavailable",
            "status": "skipped",
            "severity": "info",
            "message": "No governed physical-table boundary was available for scope verification.",
        }]

    unexpected = [
        table for table in affected
        if not _within_governed_scope(table, governed)
    ]
    if unexpected:
        return metric_checks + [{
            "code": "physical_scope_violation",
            "status": "failed",
            "severity": "error",
            "unexpected_tables": unexpected,
            "governed_tables": governed,
            "message": "Generated SQL references table(s) outside the governed physical context: "
            + ", ".join(unexpected),
        }]

    return metric_checks + [{
        "code": "physical_scope_alignment",
        "status": "passed",
        "severity": "info",
        "affected_tables": affected,
        "governed_tables": governed,
        "message": "All SQL table references are within the governed physical context.",
    }]
