"""Deterministic correctness checks between governed context and generated SQL."""

from __future__ import annotations

from typing import Any, Iterable

from sqlglot import exp, parse_one

from datapilot.infrastructure.sql.dialects import sqlglot_dialect


def _normalise(name: str) -> str:
    return str(name or "").strip().strip('"').casefold()


def _canonical_table_name(table: str, *, dialect: str) -> str:
    """Return schema-qualified table identity without SQL quoting or aliases."""
    value = str(table or "").strip()
    if not value:
        return ""
    try:
        parsed = parse_one(value, read=sqlglot_dialect(dialect), into=exp.Table)
        table_name = _normalise(parsed.name)
        schema_name = _normalise(parsed.db)
        return f"{schema_name}.{table_name}" if schema_name else table_name
    except Exception:
        # Keep scope verification available for validator formats that are not
        # independently parseable as a Table expression.
        base = value.split(" AS ", 1)[0].split(" as ", 1)[0].strip()
        return ".".join(
            _normalise(part.strip())
            for part in base.split(".")
            if part.strip()
        )


def _within_governed_scope(table: str, governed_tables: Iterable[str], *, dialect: str) -> bool:
    candidate = _canonical_table_name(table, dialect=dialect)
    candidate_leaf = candidate.rsplit(".", 1)[-1]
    for governed in governed_tables:
        allowed = _canonical_table_name(governed, dialect=dialect)
        if candidate == allowed:
            return True
        # Validators may report either schema-qualified or unqualified names.
        if candidate_leaf == allowed.rsplit(".", 1)[-1]:
            return True
    return False


def _canonical_expression(expression: exp.Expression, *, dialect: str) -> str:
    """Canonicalize a row-level expression while ignoring SQL aliases/qualifiers."""
    copy = expression.copy()
    for column in copy.find_all(exp.Column):
        column.set("table", None)
        column.set("db", None)
        column.set("catalog", None)
        # Governed metadata may store identifiers unquoted while generated SQL
        # quotes them. Identifier quoting/case is not part of metric semantics.
        column.set("this", exp.to_identifier(_normalise(column.name), quoted=False))
    return copy.sql(dialect=sqlglot_dialect(dialect)).casefold().replace(" ", "")


def _metric_expression_checks(sql: str, governed_metrics: Iterable[dict[str, Any]], *, dialect: str) -> list[dict[str, Any]]:
    derived = [
        metric for metric in governed_metrics
        if str(metric.get("calculation_expression") or "").strip()
    ]
    if not derived:
        return []

    try:
        tree = parse_one(sql, read=sqlglot_dialect(dialect))
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
            expected = _canonical_expression(parse_one(expression_sql, read=sqlglot_dialect(dialect)), dialect=dialect)
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
            if argument is not None and _canonical_expression(argument, dialect=dialect) == expected:
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



def _grouping_checks(
    sql: str,
    *,
    required_grouping_columns: Iterable[str],
    dialect: str,
) -> list[dict[str, Any]]:
    required = {
        _normalise(column).rsplit(".", 1)[-1]
        for column in required_grouping_columns
        if str(column or "").strip()
    }
    if not required:
        return []

    try:
        tree = parse_one(sql, read=sqlglot_dialect(dialect))
    except Exception:
        return [{
            "code": "grouping_verification_unavailable",
            "status": "skipped",
            "severity": "info",
            "message": "Grouping verification could not parse the validated SQL.",
        }]

    group = tree.args.get("group")
    actual: set[str] = set()
    if group is not None:
        for expression in group.expressions:
            for column in expression.find_all(exp.Column):
                actual.add(_normalise(column.name))

    missing = sorted(required - actual)
    if missing:
        return [{
            "code": "grouping_dimension_violation",
            "status": "failed",
            "severity": "error",
            "required_columns": sorted(required),
            "actual_grouping_columns": sorted(actual),
            "missing_columns": missing,
            "message": "Generated SQL does not group by all governed dimensions: " + ", ".join(missing),
        }]

    return [{
        "code": "grouping_dimension_alignment",
        "status": "passed",
        "severity": "info",
        "required_columns": sorted(required),
        "actual_grouping_columns": sorted(actual),
        "message": "SQL grouping contains all governed dimensions required by the question.",
    }]



def _filter_checks(
    sql: str,
    *,
    required_filters: Iterable[dict[str, Any]],
    dialect: str,
) -> list[dict[str, Any]]:
    """Verify deterministic semantic filters are represented in SQL predicates."""
    filters = [
        item for item in required_filters
        if str(item.get("column_name") or "").strip()
    ]
    if not filters:
        return []

    try:
        tree = parse_one(sql, read=sqlglot_dialect(dialect))
    except Exception:
        return [{
            "code": "filter_verification_unavailable",
            "status": "skipped",
            "severity": "info",
            "message": "Filter verification could not parse the validated SQL.",
        }]

    operator_nodes: dict[str, type[exp.Expression]] = {
        "=": exp.EQ,
        "!=": exp.NEQ,
        "<>": exp.NEQ,
        ">": exp.GT,
        ">=": exp.GTE,
        "<": exp.LT,
        "<=": exp.LTE,
    }
    checks: list[dict[str, Any]] = []

    def literal_value(node: exp.Expression | None) -> str | None:
        if isinstance(node, exp.Literal):
            return str(node.this)
        if isinstance(node, exp.Boolean):
            return str(node.this).casefold()
        if isinstance(node, exp.Null):
            return "null"
        return None

    for item in filters:
        column_name = _normalise(str(item.get("column_name") or "")).rsplit(".", 1)[-1]
        operator = str(item.get("operator") or "=").strip()
        expected_value = str(item.get("value") or "")
        node_type = operator_nodes.get(operator)
        if node_type is None:
            checks.append({
                "code": "filter_verification_unavailable",
                "status": "skipped",
                "severity": "info",
                "column": column_name,
                "operator": operator,
                "message": f"Filter verification does not yet support operator {operator}.",
            })
            continue

        matched = False
        for predicate in tree.find_all(node_type):
            left_columns = {
                _normalise(column.name) for column in predicate.this.find_all(exp.Column)
            } if predicate.this is not None else set()
            right_columns = {
                _normalise(column.name) for column in predicate.expression.find_all(exp.Column)
            } if predicate.expression is not None else set()

            if column_name in left_columns:
                actual = literal_value(predicate.expression)
            elif column_name in right_columns and operator == "=":
                actual = literal_value(predicate.this)
            else:
                continue

            if actual is not None and actual.casefold() == expected_value.casefold():
                matched = True
                break

        if matched:
            checks.append({
                "code": "filter_alignment",
                "status": "passed",
                "severity": "info",
                "attribute": item.get("attribute"),
                "column": column_name,
                "operator": operator,
                "value": expected_value,
                "message": f"SQL contains the governed filter on {column_name}.",
            })
        else:
            checks.append({
                "code": "filter_violation",
                "status": "failed",
                "severity": "error",
                "attribute": item.get("attribute"),
                "column": column_name,
                "operator": operator,
                "expected_value": expected_value,
                "message": f"Generated SQL does not contain the governed filter {column_name} {operator} {expected_value!r}.",
            })
    return checks



def _relationship_checks(
    sql: str,
    *,
    required_relationships: Iterable[dict[str, Any]],
    dialect: str,
) -> list[dict[str, Any]]:
    """Verify governed relationships are represented by SQL equality joins."""
    relationships = [
        item for item in required_relationships
        if str(item.get("from_column") or "").strip()
        and str(item.get("to_column") or "").strip()
    ]
    if not relationships:
        return []

    try:
        tree = parse_one(sql, read=sqlglot_dialect(dialect))
    except Exception:
        return [{
            "code": "relationship_verification_unavailable",
            "status": "skipped",
            "severity": "info",
            "message": "Relationship verification could not parse the validated SQL.",
        }]

    alias_to_table: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        table_name = _normalise(table.name)
        schema_name = _normalise(table.db)
        qualified = f"{schema_name}.{table_name}" if schema_name else table_name
        alias = _normalise(table.alias_or_name)
        if alias:
            alias_to_table[alias] = qualified
        alias_to_table[table_name] = qualified

    def column_ref(column: exp.Column) -> tuple[str, str]:
        qualifier = _normalise(column.table)
        table_name = alias_to_table.get(qualifier, qualifier)
        return table_name, _normalise(column.name)

    equality_pairs: set[frozenset[tuple[str, str]]] = set()
    for predicate in tree.find_all(exp.EQ):
        if isinstance(predicate.this, exp.Column) and isinstance(predicate.expression, exp.Column):
            equality_pairs.add(frozenset({
                column_ref(predicate.this),
                column_ref(predicate.expression),
            }))

    checks: list[dict[str, Any]] = []
    for relationship in relationships:
        name = str(relationship.get("name") or "relationship")
        from_table = _normalise(str(relationship.get("from_table") or ""))
        to_table = _normalise(str(relationship.get("to_table") or ""))
        from_column = _normalise(str(relationship.get("from_column") or ""))
        to_column = _normalise(str(relationship.get("to_column") or ""))

        expected = frozenset({
            (from_table, from_column),
            (to_table, to_column),
        })
        matched = expected in equality_pairs
        checks.append({
            "code": "relationship_alignment" if matched else "relationship_violation",
            "status": "passed" if matched else "failed",
            "severity": "info" if matched else "error",
            "relationship": name,
            "from_table": from_table,
            "from_column": from_column,
            "to_table": to_table,
            "to_column": to_column,
            "message": (
                f"SQL uses the governed join path for {name}."
                if matched else
                f"Generated SQL does not use the governed join path for {name}: "
                f"{from_table}.{from_column} = {to_table}.{to_column}."
            ),
        })
    return checks



def _fanout_checks(
    sql: str,
    *,
    governed_metrics: Iterable[dict[str, Any]],
    required_relationships: Iterable[dict[str, Any]],
    dialect: str,
) -> list[dict[str, Any]]:
    """Detect additive/non-distinct metrics crossing from a one-side entity to many.

    A correct join predicate can still multiply a metric when its owning entity is
    on the one-side of a one-to-many relationship. COUNT DISTINCT is inherently
    protected. Complex subquery/pre-aggregation plans are not guessed about here.
    """
    metrics = list(governed_metrics)
    relationships = list(required_relationships)
    if not metrics or not relationships:
        return []

    try:
        tree = parse_one(sql, read=sqlglot_dialect(dialect))
    except Exception:
        return [{
            "code": "fanout_verification_unavailable",
            "status": "skipped",
            "severity": "info",
            "message": "Join fan-out verification could not parse the validated SQL.",
        }]

    # Verify the join grain of a simple aggregated derived table. This is
    # diagnostic evidence only, not a waiver of governed fan-out violations.
    grain_checks: list[dict[str, Any]] = []
    for join in tree.find_all(exp.Join):
        derived = join.this
        if not isinstance(derived, exp.Subquery) or not isinstance(derived.this, exp.Select):
            continue
        inner = derived.this
        if not inner.args.get("group") and not inner.find(exp.AggFunc):
            continue
        alias = str(derived.alias_or_name or "").casefold()
        on = join.args.get("on")
        joined_key = None
        if isinstance(on, exp.EQ):
            for left, right in ((on.left, on.right), (on.right, on.left)):
                if isinstance(left, exp.Column) and isinstance(right, exp.Column) and str(left.table or "").casefold() == alias:
                    joined_key = str(left.name).casefold()
                    break
        projected_keys = set()
        for projection in inner.expressions:
            if isinstance(projection, exp.Column):
                projected_keys.add((str(projection.alias_or_name).casefold(), str(projection.name).casefold()))
            elif isinstance(projection, exp.Alias) and isinstance(projection.this, exp.Column):
                projected_keys.add((str(projection.alias).casefold(), str(projection.this.name).casefold()))
        grouping = inner.args.get("group")
        grouped_columns = {str(col.name).casefold() for col in grouping.expressions if isinstance(col, exp.Column)} if grouping else set()
        grain_proven = bool(joined_key and any(alias_name == joined_key and physical_name in grouped_columns for alias_name, physical_name in projected_keys))
        # Require a simple column-only GROUP BY and prohibit DISTINCT / grouping sets.
        grain_proven = (grain_proven and bool(grouping)
                        and all(isinstance(item, exp.Column) for item in grouping.expressions)
                        and len(grouping.expressions) == 1
                        and not inner.args.get("distinct")
                        and not inner.args.get("having")
                        and not inner.args.get("qualify")
                        and not inner.args.get("limit")
                        and not inner.args.get("offset")
                        and not any(isinstance(node, exp.Window) for node in inner.walk())
                        and not inner.args.get("joins")
                        and not inner.args.get("with_")
                        and not any(isinstance(node, (exp.Subquery, exp.CTE, exp.Union)) for node in inner.walk()))
        grain_checks.append({
            "code": "preaggregation_grain_alignment" if grain_proven else "preaggregation_grain_unverified",
            "status": "passed" if grain_proven else "skipped",
            "severity": "info",
            "message": "Derived dataset is grouped by its projected join key." if grain_proven else "Derived dataset join-key uniqueness was not established.",
        })

    # Do not mark a pre-aggregated plan safe merely because it is nested.
    # Cardinality checks below still apply; a separate grain proof is needed
    # before allowing otherwise risky one-to-many aggregation.
    def cardinality_sides(value: str) -> tuple[str, str] | None:
        normalized = str(value or "").strip().casefold().replace("_", "-").replace(" ", "-")
        normalized = normalized.replace("many-to-one", "many-one").replace("one-to-many", "one-many")
        normalized = normalized.replace("one-to-one", "one-one").replace("many-to-many", "many-many")
        parts = normalized.split("-")
        if len(parts) == 2 and all(part in {"one", "many"} for part in parts):
            return parts[0], parts[1]
        return None

    # Metric lineage is advisory until semantic entity-to-table provenance is
    # available. Verify an explicit physical source column in an aggregate,
    # rather than inferring ownership from the metric's display name.
    lineage_checks: list[dict[str, Any]] = []
    for metric in metrics:
        source_column = str(metric.get("column_name") or "").strip().casefold()
        source_table = str(metric.get("table_name") or "").strip().casefold()
        if not source_column or not source_table:
            continue
        source_parts = source_table.split(".")
        source_name = source_parts[-1]
        source_schema = source_parts[-2] if len(source_parts) > 1 else None
        # Resolve each aggregate column in its own SELECT block. A reused
        # alias in an independent subquery is not the same physical source.
        def select_scope(node: exp.Expression) -> exp.Select | None:
            parent = node.parent
            while parent is not None and not isinstance(parent, exp.Select):
                parent = parent.parent
            return parent if isinstance(parent, exp.Select) else None

        def local_tables(scope: exp.Select) -> list[exp.Table]:
            sources = []
            from_clause = scope.args.get("from_")
            if from_clause is not None and isinstance(from_clause.this, exp.Table):
                sources.append(from_clause.this)
            for join in scope.args.get("joins") or []:
                if isinstance(join.this, exp.Table):
                    sources.append(join.this)
            return sources

        # Every column used by every aggregate must resolve to the declared
        # metric source. A matching column somewhere in an expression is not
        # sufficient evidence (e.g. SUM(p.amount + p.other_amount)).
        aggregates = list(tree.find_all(exp.AggFunc))
        aggregate_columns = [
            column for aggregate in aggregates
            for column in aggregate.find_all(exp.Column)
        ]
        direct_inputs = all(
            not list(aggregate.find_all(exp.Column))
            or (
                len(list(aggregate.find_all(exp.Column))) == 1
                and isinstance(aggregate.this, exp.Column)
            )
            for aggregate in aggregates
        )
        resolved_columns = []
        for column in aggregate_columns:
            scope = select_scope(column)
            alias = str(column.table or "").casefold()
            if scope is None or not alias:
                resolved_columns.append(False)
                continue
            candidates = [
                table for table in local_tables(scope)
                if str(table.alias_or_name).casefold() == alias
            ]
            resolved_columns.append(
                len(candidates) == 1
                and str(column.name).casefold() == source_column
                and str(candidates[0].name).casefold() == source_name
                and (source_schema is None or str(candidates[0].db or "").casefold() == source_schema)
            )
        verified = bool(aggregates) and direct_inputs and bool(aggregate_columns) and all(resolved_columns)
        # A narrow derived-table case: SUM(d.metric_alias) over a direct
        # projection of one physical source column. No nested joins, stars,
        # expressions or ambiguous alias resolution are treated as proof.
        if not verified and direct_inputs:
            # Derived projection names can differ from the physical column.
            # Check every aggregate input, not only names matching the source.
            derived_inputs = [
                column for aggregate in tree.find_all(exp.AggFunc)
                for column in aggregate.find_all(exp.Column)
            ]
            derived_resolutions = []
            for column in derived_inputs:
                scope = select_scope(column)
                alias = str(column.table or "").casefold()
                outer_from = scope.args.get("from_") if scope is not None else None
                derived = outer_from.this if outer_from is not None else None
                if (
                    not isinstance(derived, exp.Subquery)
                    or str(derived.alias_or_name or "").casefold() != alias
                    or not isinstance(derived.this, exp.Select)
                    or scope.args.get("joins")
                ):
                    derived_resolutions.append(False)
                    continue
                inner = derived.this
                inner_from = inner.args.get("from_")
                physical = inner_from.this if inner_from is not None else None
                if (
                    not isinstance(physical, exp.Table)
                    or inner.args.get("joins")
                    or inner.args.get("with_")
                    or inner.args.get("group")
                    or inner.args.get("distinct")
                    or inner.args.get("limit")
                    or inner.args.get("offset")
                    or any(isinstance(node, (exp.Subquery, exp.CTE, exp.Union, exp.AggFunc, exp.Window))
                           for node in inner.walk())
                ):
                    derived_resolutions.append(False)
                    continue
                projections = [
                    projection for projection in inner.expressions
                    if str(projection.alias_or_name or "").casefold() == str(column.name).casefold()
                ]
                projected = projections[0] if len(projections) == 1 else None
                projected_column = projected.this if isinstance(projected, exp.Alias) else projected
                derived_resolutions.append(
                    len(projections) == 1
                    and isinstance(projected_column, exp.Column)
                    and str(projected_column.name).casefold() == source_column
                    and str(projected_column.table or "").casefold() == str(physical.alias_or_name).casefold()
                    and str(physical.name).casefold() == source_name
                    and (source_schema is None or str(physical.db or "").casefold() == source_schema)
                )
            verified = bool(derived_resolutions) and all(derived_resolutions)
        lineage_checks.append({
            "code": "metric_lineage_alignment" if verified else "metric_lineage_unverified",
            "status": "passed" if verified else "skipped",
            "severity": "info",
            "metric": str(metric.get("name") or "metric"),
            "message": "Aggregate references the declared physical metric source." if verified
                       else "Metric source could not be established from the SQL aggregate.",
        })

    checks: list[dict[str, Any]] = []
    for metric in metrics:
        metric_entity_id = metric.get("entity_id")
        aggregation = str(metric.get("aggregation") or "").strip().casefold()
        metric_name = str(metric.get("name") or "metric")
        if metric_entity_id is None or aggregation in {"count_distinct", "min", "max"}:
            continue

        for relationship in relationships:
            sides = cardinality_sides(str(relationship.get("cardinality") or ""))
            if sides is None:
                continue
            from_side, to_side = sides
            from_id = relationship.get("from_entity_id")
            to_id = relationship.get("to_entity_id")

            # Fan-out occurs when the metric lives on the ONE side and the query
            # traverses the governed relationship to its MANY side.
            risky = (
                metric_entity_id == from_id and from_side == "one" and to_side == "many"
            ) or (
                metric_entity_id == to_id and to_side == "one" and from_side == "many"
            )
            if not risky:
                continue

            # Report the intersection of semantic ownership and physical SQL
            # lineage without treating either as a fan-out safety waiver.
            # The SQL may still multiply rows even with correct metric lineage.
            lineage_evidence = next(
                (item for item in lineage_checks if item.get("metric") == metric_name),
                None,
            )
            if lineage_evidence is not None:
                checks.append({
                    "code": "fanout_metric_ownership_confirmed"
                    if lineage_evidence["code"] == "metric_lineage_alignment"
                    else "fanout_metric_ownership_unverified",
                    "status": "passed" if lineage_evidence["code"] == "metric_lineage_alignment" else "skipped",
                    "severity": "info",
                    "metric": metric_name,
                    "relationship": relationship.get("name"),
                    "message": (
                        "Metric physical lineage agrees with its declared source, "
                        "but the relationship can still multiply rows."
                        if lineage_evidence["code"] == "metric_lineage_alignment"
                        else "Metric physical ownership is not proven for this risky relationship."
                    ),
                })

            # Aggregate all three independent proof obligations. A verified
            # derived-table grain is not proof that the metric's join is safe:
            # the metric must also be traced to its governed physical source,
            # and the relationship must be shown not to multiply metric rows.
            ownership_confirmed = (
                lineage_evidence is not None
                and lineage_evidence["code"] == "metric_lineage_alignment"
            )
            grain_confirmed = any(
                item.get("code") == "preaggregation_grain_alignment"
                and item.get("status") == "passed"
                for item in grain_checks
            )
            # Structural join-key evidence is scoped to an individual JOIN.
            # This is intentionally not a uniqueness/cardinality proof.
            joined_grain_keys = []
            for join in tree.find_all(exp.Join):
                derived = join.this
                on = join.args.get("on")
                if not isinstance(derived, exp.Subquery) or not isinstance(derived.this, exp.Select):
                    continue
                if not isinstance(on, exp.EQ):
                    continue
                alias = str(derived.alias_or_name or "").casefold()
                joined_column = None
                for left, right in ((on.left, on.right), (on.right, on.left)):
                    if (
                        isinstance(left, exp.Column)
                        and isinstance(right, exp.Column)
                        and str(left.table or "").casefold() == alias
                        and str(right.table or "").casefold() != alias
                    ):
                        joined_column = str(left.name).casefold()
                        break
                if not joined_column:
                    continue
                inner = derived.this
                grouping = inner.args.get("group")
                if grouping is None or len(grouping.expressions) != 1:
                    continue
                grouped = grouping.expressions[0]
                if not isinstance(grouped, exp.Column):
                    continue
                if any(
                    str(projection.alias_or_name or "").casefold() == joined_column
                    and isinstance(projection.this if isinstance(projection, exp.Alias) else projection, exp.Column)
                    and str((projection.this if isinstance(projection, exp.Alias) else projection).name).casefold()
                    == str(grouped.name).casefold()
                    for projection in inner.expressions
                ):
                    joined_grain_keys.append(f"{alias}.{joined_column}")
            checks.append({
                "code": "fanout_join_grain_key_observed" if joined_grain_keys else "fanout_join_grain_key_unverified",
                "status": "passed" if joined_grain_keys else "skipped",
                "severity": "info",
                "metric": metric_name,
                "relationship": relationship.get("name"),
                "joined_grain_keys": joined_grain_keys,
                "message": (
                    "An equality join references a derived grouping key; this does not establish "
                    "metric-row uniqueness or override fan-out protection."
                    if joined_grain_keys else
                    "No simple derived grouping-key equality join was identified."
                ),
            })
            # A grouping-key observation only covers one edge. Record whether
            # every JOIN in the outer SELECT has that structural evidence.
            # Nested JOINs, additional direct joins and other join types must
            # not silently inherit a single derived table's grain evidence.
            outer_joins = list(tree.args.get("joins") or []) if isinstance(tree, exp.Select) else []
            all_outer_joins_covered = (
                bool(outer_joins)
                and len(joined_grain_keys) == len(outer_joins)
                and all(
                    isinstance(join.this, exp.Subquery)
                    and isinstance(join.this.this, exp.Select)
                    and not join.this.this.args.get("joins")
                    and not any(isinstance(node, (exp.Subquery, exp.CTE, exp.Union))
                                for node in join.this.this.walk())
                    for join in outer_joins
                )
            )
            checks.append({
                "code": "fanout_join_coverage_observed"
                if all_outer_joins_covered else "fanout_join_coverage_incomplete",
                "status": "passed" if all_outer_joins_covered else "skipped",
                "severity": "info",
                "metric": metric_name,
                "relationship": relationship.get("name"),
                "outer_join_count": len(outer_joins),
                "observed_grain_key_count": len(joined_grain_keys),
                "message": (
                    "Every outer join has a derived grouping-key observation; "
                    "this is not a cardinality or fan-out safety proof."
                    if all_outer_joins_covered else
                    "At least one join lacks independent derived grouping-key evidence."
                ),
            })
            checks.append({
                "code": "fanout_safety_evidence_incomplete",
                "status": "skipped",
                "severity": "info",
                "metric": metric_name,
                "relationship": relationship.get("name"),
                "metric_ownership_verified": ownership_confirmed,
                "preaggregation_grain_verified": grain_confirmed,
                "join_cardinality_safe": False,
                "message": (
                    "Metric ownership and preaggregation grain are evidence only; "
                    "the governed one-to-many join still lacks a non-multiplication proof."
                    if ownership_confirmed and grain_confirmed
                    else "Fan-out safety cannot be established from the available "
                         "metric ownership, grain, and cardinality evidence."
                ),
            })

            checks.append({
                "code": "join_fanout_violation",
                "status": "failed",
                "severity": "error",
                "metric": metric_name,
                "aggregation": aggregation,
                "relationship": relationship.get("name"),
                "cardinality": relationship.get("cardinality"),
                "message": (
                    f"{metric_name} is aggregated from the one-side of governed relationship "
                    f"{relationship.get('name')}; joining the many-side can duplicate metric rows. "
                    "Use a fan-out-safe grain, pre-aggregation, or COUNT DISTINCT where semantically valid."
                ),
            })

    if checks:
        return lineage_checks + grain_checks + checks

    return lineage_checks + grain_checks + [{
        "code": "join_fanout_alignment",
        "status": "passed",
        "severity": "info",
        "message": "No governed metric is exposed to a direct one-to-many aggregation fan-out.",
    }]



def _time_checks(
    sql: str,
    *,
    required_time_plan: dict[str, Any] | None,
    dialect: str,
) -> list[dict[str, Any]]:
    """Verify resolved governed time filters and grouping grain in generated SQL."""
    plan = required_time_plan or {}
    if not plan or plan.get("status") != "resolved":
        return []

    try:
        tree = parse_one(sql, read=sqlglot_dialect(dialect))
    except Exception:
        return [{
            "code": "time_verification_unavailable",
            "status": "skipped",
            "severity": "info",
            "message": "Time correctness verification could not parse the validated SQL.",
        }]

    column_name = _normalise(str(plan.get("column_name") or ""))
    if not column_name:
        return []

    def contains_time_column(node: exp.Expression | None) -> bool:
        return bool(node) and any(
            _normalise(column.name) == column_name
            for column in node.find_all(exp.Column)
        )

    def scalar_text(node: exp.Expression | None) -> str | None:
        current = node
        while isinstance(current, (exp.Cast, exp.Paren)):
            current = current.this
        if isinstance(current, (exp.Literal, exp.Var, exp.Identifier)):
            return str(current.this)
        return None

    checks: list[dict[str, Any]] = []

    comparison_periods = plan.get("periods") if plan.get("comparison") else None
    if comparison_periods:
        periods = comparison_periods
        expected_start = min(str(period["start"]) for period in periods)
        expected_end = max(str(period["end_exclusive"]) for period in periods)
    else:
        expected_start = plan.get("start")
        expected_end = plan.get("end_exclusive")

    if expected_start and expected_end:
        lower_ok = False
        upper_ok = False
        for predicate in tree.find_all(exp.GTE):
            if contains_time_column(predicate.this) and scalar_text(predicate.expression) == str(expected_start):
                lower_ok = True
            elif contains_time_column(predicate.expression) and scalar_text(predicate.this) == str(expected_start):
                # literal <= column is equivalent to column >= literal.
                lower_ok = True
        for predicate in tree.find_all(exp.LT):
            if contains_time_column(predicate.this) and scalar_text(predicate.expression) == str(expected_end):
                upper_ok = True
        if lower_ok and upper_ok:
            checks.append({
                "code": "time_filter_alignment",
                "status": "passed",
                "severity": "info",
                "column": column_name,
                "start": str(expected_start),
                "end_exclusive": str(expected_end),
                "message": "SQL uses the governed half-open time range on the governed time column.",
            })
        else:
            checks.append({
                "code": "time_filter_violation",
                "status": "failed",
                "severity": "error",
                "column": column_name,
                "start": str(expected_start),
                "end_exclusive": str(expected_end),
                "missing_lower_bound": not lower_ok,
                "missing_upper_bound": not upper_ok,
                "message": "Generated SQL does not preserve the resolved governed half-open time range.",
            })

    if comparison_periods:
        sql_text = sql.casefold()
        missing_period_boundaries: list[str] = []
        for period in comparison_periods:
            for boundary_name in ("start", "end_exclusive"):
                boundary = str(period.get(boundary_name) or "")
                if boundary and boundary.casefold() not in sql_text:
                    missing_period_boundaries.append(boundary)
        if missing_period_boundaries:
            checks.append({
                "code": "time_comparison_violation",
                "status": "failed",
                "severity": "error",
                "column": column_name,
                "missing_period_boundaries": sorted(set(missing_period_boundaries)),
                "message": "Generated SQL does not preserve every governed comparison-period boundary.",
            })
        else:
            checks.append({
                "code": "time_comparison_alignment",
                "status": "passed",
                "severity": "info",
                "column": column_name,
                "message": "SQL preserves every governed comparison-period boundary.",
            })

    grain = str(plan.get("grouping_grain") or "").strip().casefold()
    if grain:
        group = tree.args.get("group")
        grain_ok = False
        if group is not None:
            for expression in group.expressions:
                # sqlglot represents PostgreSQL DATE_TRUNC as TimestampTrunc in
                # current releases (older releases used DateTrunc). Inspect the
                # normalized AST shape instead of coupling correctness to one
                # concrete sqlglot expression class.
                for function in expression.walk():
                    key = str(getattr(function, "key", "") or "").casefold().replace("_", "")
                    if key not in {"datetrunc", "timestamptrunc", "datetimetrunc"}:
                        continue

                    unit_node = function.args.get("unit")
                    target = function.args.get("this")
                    if unit_node is None:
                        # Compatibility with the older DateTrunc AST shape.
                        unit_node = function.args.get("this")
                        target = function.args.get("expression")

                    unit = scalar_text(unit_node)
                    if unit and unit.casefold() == grain and contains_time_column(target):
                        grain_ok = True
                        break
                if grain_ok:
                    break

        checks.append({
            "code": "time_grain_alignment" if grain_ok else "time_grain_violation",
            "status": "passed" if grain_ok else "failed",
            "severity": "info" if grain_ok else "error",
            "column": column_name,
            "grain": grain,
            "message": (
                f"SQL groups the governed time column at {grain} grain."
                if grain_ok else
                f"Generated SQL does not group the governed time column at the resolved {grain} grain."
            ),
        })

    return checks

def assess_query_correctness(
    *,
    affected_tables: Iterable[str],
    governed_tables: Iterable[str],
    sql: str | None = None,
    governed_metrics: Iterable[dict[str, Any]] = (),
    required_grouping_columns: Iterable[str] = (),
    required_filters: Iterable[dict[str, Any]] = (),
    required_relationships: Iterable[dict[str, Any]] = (),
    required_time_plan: dict[str, Any] | None = None,
    dialect: str = "postgresql",
) -> list[dict[str, Any]]:
    """Return deterministic pre-execution alignment checks.

    This deliberately does not ask an LLM to judge its own SQL. The first
    production invariant is physical-scope containment: generated SQL may only
    touch tables selected by the governed semantic/physical context.
    """
    affected = [str(item) for item in affected_tables if str(item or "").strip()]
    governed = [str(item) for item in governed_tables if str(item or "").strip()]

    metric_checks = _metric_expression_checks(sql, governed_metrics, dialect=dialect) if sql else []
    grouping_checks = _grouping_checks(
        sql,
        required_grouping_columns=required_grouping_columns,
        dialect=dialect,
    ) if sql else []
    filter_checks = _filter_checks(sql, required_filters=required_filters, dialect=dialect) if sql else []
    required_relationships = list(required_relationships)
    relationship_checks = _relationship_checks(sql, required_relationships=required_relationships, dialect=dialect) if sql else []
    # The join graph is authoritative for SQL containing multiple physical joins.
    # Do not silently skip governance when the context exposes only one edge.
    from datapilot.application.join_policy_governance import (
        validate_governed_join_policy, validate_governed_join_graph,
    )
    join_policy_checks = []
    if sql and required_relationships:
        try:
            parsed = parse_one(sql, read=sqlglot_dialect(dialect))
            join_count = len(list(parsed.find_all(exp.Join)))
        except Exception:
            parsed = None
            join_count = 0
        if join_count > 1 or len(required_relationships) > 1 or (parsed is not None and (parsed.args.get("with_") is not None or any(isinstance(node, exp.Subquery) for node in parsed.walk()))):
            decision = validate_governed_join_graph(sql, required_relationships)
            join_policy_checks.append({
                "code": "join_policy_alignment" if decision.allowed else "join_policy_violation",
                "status": "passed" if decision.allowed else "failed",
                "severity": "info" if decision.allowed else "error",
                "relationship": "governed_join_graph",
                "message": "Every join edge follows an approved policy." if decision.allowed else "; ".join(decision.reasons),
            })
        else:
            for relationship in required_relationships:
                if "join_policy" not in relationship:
                    continue
                decision = validate_governed_join_policy(sql, relationship)
                join_policy_checks.append({
                    "code": "join_policy_alignment" if decision.allowed else "join_policy_violation",
                    "status": "passed" if decision.allowed else "failed",
                    "severity": "info" if decision.allowed else "error",
                    "relationship": str(relationship.get("name") or "relationship"),
                    "message": "Approved join policy is enforced." if decision.allowed else "; ".join(decision.reasons),
                })
    fanout_checks = _fanout_checks(sql, governed_metrics=governed_metrics, required_relationships=required_relationships, dialect=dialect) if sql else []
    time_checks = _time_checks(sql, required_time_plan=required_time_plan, dialect=dialect) if sql else []
    semantic_checks = metric_checks + grouping_checks + filter_checks + relationship_checks + join_policy_checks + fanout_checks + time_checks

    if not governed:
        return semantic_checks + [{
            "code": "governed_scope_unavailable",
            "status": "skipped",
            "severity": "info",
            "message": "No governed physical-table boundary was available for scope verification.",
        }]

    unexpected = [
        table for table in affected
        if not _within_governed_scope(table, governed, dialect=dialect)
    ]
    if unexpected:
        return semantic_checks + [{
            "code": "physical_scope_violation",
            "status": "failed",
            "severity": "error",
            "unexpected_tables": unexpected,
            "governed_tables": governed,
            "message": "Generated SQL references table(s) outside the governed physical context: "
            + ", ".join(unexpected),
        }]

    return semantic_checks + [{
        "code": "physical_scope_alignment",
        "status": "passed",
        "severity": "info",
        "affected_tables": affected,
        "governed_tables": governed,
        "message": "All SQL table references are within the governed physical context.",
    }]
