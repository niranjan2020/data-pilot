"""Conservative PostgreSQL projection compiler for governed analytical plans.

Only a single-source, single-step dimension projection is supported.
All other operation graphs fail closed. No user-supplied SQL fragments are
accepted, and compilation does not execute queries.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from datapilot.application.services.analytical_plan import AnalyticalOperation
from datapilot.application.services.unified_analytical_binding import (
    UnifiedPhysicalAnalyticalPlan,
)


@dataclass(frozen=True)
class CompiledAnalyticalQuery:
    sql: str
    dialect: str = "postgres"
    parameters: tuple = ()


def _quote_identifier(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Invalid governed SQL identifier")
    return '"' + value.replace('"', '""') + '"'


def compile_analytical_projection(
    physical_plan: UnifiedPhysicalAnalyticalPlan,
) -> CompiledAnalyticalQuery:
    """Compile a single published dimension projection, or reject the plan.

    No JOIN, WHERE, aggregation, expression or user-supplied physical
    identifiers are supported. This is not an execution authorization gate.
    """
    if not isinstance(physical_plan, UnifiedPhysicalAnalyticalPlan):
        raise ValueError("Unified governed physical plan is required")
    bound = physical_plan.bound_plan
    plan = bound.plan
    if len(plan.sources) != 1 or len(plan.steps) != 1:
        raise ValueError("Unsupported analytical projection graph")
    step = plan.steps[0]
    if step.operation is not AnalyticalOperation.PROJECT or step.inputs != plan.sources:
        raise ValueError("Unsupported analytical projection operation")
    if set(step.parameters) != {"dimension"}:
        raise ValueError("Projection requires only one governed dimension")
    if len(physical_plan.dimensions) != 1 or physical_plan.metrics or physical_plan.time_dimensions:
        raise ValueError("Projection requires exactly one approved physical dimension")
    mapping = physical_plan.dimensions[0]
    if mapping.step_id != step.id or mapping.parameter != "dimension":
        raise ValueError("Physical dimension does not match projection step")
    if len(bound.references) != 1 or bound.references[0].kind != "dimension":
        raise ValueError("Projection requires a governed dimension reference")
    if not all(
        isinstance(value, str) and value and "\x00" not in value
        for value in (mapping.schema_name, mapping.table_name, mapping.column_name)
    ):
        raise ValueError("Incomplete physical dimension mapping")
    column = _quote_identifier(mapping.column_name)
    schema = _quote_identifier(mapping.schema_name)
    table = _quote_identifier(mapping.table_name)
    return CompiledAnalyticalQuery(
        sql=f"SELECT {column} FROM {schema}.{table}"
    )


@dataclass(frozen=True)
class GovernedMetricSource:
    """Trusted physical source mapping for one published metric."""
    entity_id: int
    schema_name: str
    table_name: str
    column_name: str


def compile_analytical_aggregation(
    physical_plan: UnifiedPhysicalAnalyticalPlan,
    *,
    metric_source: GovernedMetricSource,
) -> CompiledAnalyticalQuery:
    """Compile only a single-table, single-metric approved aggregation.

    The metric source must be resolved from trusted catalog metadata, not
    request input. Calculated expressions and unverified joins are rejected.
    This compiler does not authorize execution or enforce dataset policies.
    """
    if not isinstance(physical_plan, UnifiedPhysicalAnalyticalPlan):
        raise ValueError("Unified governed physical plan is required")
    if not isinstance(metric_source, GovernedMetricSource):
        raise ValueError("Governed metric source is required")
    plan = physical_plan.bound_plan.plan
    if len(plan.sources) != 1 or len(plan.steps) != 1:
        raise ValueError("Unsupported analytical aggregation graph")
    step = plan.steps[0]
    if step.operation is not AnalyticalOperation.AGGREGATE or step.inputs != plan.sources:
        raise ValueError("Unsupported analytical aggregation operation")
    if set(step.parameters) != {"metric"}:
        raise ValueError("Aggregation requires only one governed metric")
    if len(physical_plan.metrics) != 1 or physical_plan.dimensions or physical_plan.time_dimensions:
        raise ValueError("Aggregation requires exactly one approved metric")
    if len(physical_plan.bound_plan.references) != 1:
        raise ValueError("Aggregation requires one governed reference")
    reference = physical_plan.bound_plan.references[0]
    metric = physical_plan.metrics[0]
    if (reference.kind, reference.step_id, reference.parameter) != ("metric", step.id, "metric"):
        raise ValueError("Metric reference does not match aggregation")
    if (metric.step_id, metric.parameter, metric.semantic_name) != (
        step.id, "metric", reference.name
    ):
        raise ValueError("Metric binding does not match aggregation")
    if type(metric.entity_id) is not int or metric.entity_id <= 0 or (
        type(metric_source.entity_id) is not int or metric.entity_id != metric_source.entity_id
    ):
        raise ValueError("Metric source entity mismatch")
    if metric.calculation_expression is not None:
        raise ValueError("Calculated metric expressions are not supported")
    if not isinstance(metric.attribute_name, str) or metric.attribute_name != metric_source.column_name:
        raise ValueError("Metric source column mismatch")
    if metric.aggregation not in ("SUM", "COUNT", "AVG", "MIN", "MAX"):
        raise ValueError("Unsupported governed aggregation function")
    schema = _quote_identifier(metric_source.schema_name)
    table = _quote_identifier(metric_source.table_name)
    column = _quote_identifier(metric_source.column_name)
    return CompiledAnalyticalQuery(
        sql=f'SELECT {metric.aggregation}({column}) AS "value" FROM {schema}.{table}'
    )


def compile_analytical_grouped_aggregation(
    physical_plan: UnifiedPhysicalAnalyticalPlan,
    *,
    metric_source: GovernedMetricSource,
) -> CompiledAnalyticalQuery:
    """Compile a governed group->aggregate graph on one physical entity.

    Rejects cross-entity grouping, expressions, and unverified graph shapes.
    No joins or row-level policies are inferred by this compiler.
    """
    if not isinstance(physical_plan, UnifiedPhysicalAnalyticalPlan):
        raise ValueError("Unified governed physical plan is required")
    if not isinstance(metric_source, GovernedMetricSource):
        raise ValueError("Governed metric source is required")
    bound = physical_plan.bound_plan
    plan = bound.plan
    if len(plan.sources) != 1 or len(plan.steps) != 2:
        raise ValueError("Unsupported grouped aggregation graph")
    group, aggregate = plan.steps
    if (
        group.operation is not AnalyticalOperation.GROUP
        or aggregate.operation is not AnalyticalOperation.AGGREGATE
        or group.inputs != plan.sources
        or aggregate.inputs != (group.id,)
        or plan.output != aggregate.id
    ):
        raise ValueError("Unsupported grouped aggregation operation order")
    if set(group.parameters) != {"dimension"} or set(aggregate.parameters) != {"metric"}:
        raise ValueError("Grouped aggregation requires one dimension and one metric")
    if len(physical_plan.dimensions) != 1 or len(physical_plan.metrics) != 1 or physical_plan.time_dimensions:
        raise ValueError("Grouped aggregation requires exactly one dimension and metric")
    dimension = physical_plan.dimensions[0]
    metric = physical_plan.metrics[0]
    if (
        dimension.step_id != group.id or dimension.parameter != "dimension"
        or metric.step_id != aggregate.id or metric.parameter != "metric"
    ):
        raise ValueError("Physical mappings do not match grouped plan steps")
    references = {(r.step_id, r.parameter, r.kind): r.name for r in bound.references}
    if len(bound.references) != 2 or (
        references.get((group.id, "dimension", "dimension")) != group.parameters["dimension"]
        and references.get((group.id, "dimension", "dimension")) != dimension.semantic_name
    ) or references.get((aggregate.id, "metric", "metric")) != metric.semantic_name:
        raise ValueError("Grouped aggregation governed references mismatch")
    if (
        type(metric.entity_id) is not int or metric.entity_id <= 0
        or type(dimension.entity_id) is not int
        or type(metric_source.entity_id) is not int
        or metric.entity_id != dimension.entity_id
        or metric.entity_id != metric_source.entity_id
    ):
        raise ValueError("Cross-entity grouping requires governed join validation")
    if (
        dimension.schema_name != metric_source.schema_name
        or dimension.table_name != metric_source.table_name
    ):
        raise ValueError("Grouped metric and dimension physical sources mismatch")
    if metric.calculation_expression is not None:
        raise ValueError("Calculated metric expressions are not supported")
    if not isinstance(metric.attribute_name, str) or metric.attribute_name != metric_source.column_name:
        raise ValueError("Metric source column mismatch")
    if metric.aggregation not in ("SUM", "COUNT", "AVG", "MIN", "MAX"):
        raise ValueError("Unsupported governed aggregation function")
    schema = _quote_identifier(metric_source.schema_name)
    table = _quote_identifier(metric_source.table_name)
    group_column = _quote_identifier(dimension.column_name)
    metric_column = _quote_identifier(metric_source.column_name)
    return CompiledAnalyticalQuery(
        sql=(
            f'SELECT {group_column} AS "dimension", '
            f'{metric.aggregation}({metric_column}) AS "value" '
            f'FROM {schema}.{table} GROUP BY {group_column}'
        )
    )


def compile_analytical_grouped_sort(
    physical_plan: UnifiedPhysicalAnalyticalPlan,
    *,
    metric_source: GovernedMetricSource,
) -> CompiledAnalyticalQuery:
    """Compile GROUP -> AGGREGATE -> SORT without guessing order expressions.

    Sorting targets the existing governed dimension or metric, not arbitrary
    SQL text. A bounded explicit direction is mandatory. No LIMIT is implied.
    """
    from dataclasses import replace

    from datapilot.application.services.analytical_plan import AnalyticalPlan
    from datapilot.application.services.analytical_plan_binding import BoundAnalyticalPlan

    if not isinstance(physical_plan, UnifiedPhysicalAnalyticalPlan):
        raise ValueError("Unified governed physical plan is required")
    bound = physical_plan.bound_plan
    plan = bound.plan
    if len(plan.sources) != 1 or len(plan.steps) != 3:
        raise ValueError("Unsupported sorted aggregation graph")
    group, aggregate, sort = plan.steps
    if (
        group.operation is not AnalyticalOperation.GROUP
        or aggregate.operation is not AnalyticalOperation.AGGREGATE
        or sort.operation is not AnalyticalOperation.SORT
        or group.inputs != plan.sources
        or aggregate.inputs != (group.id,)
        or sort.inputs != (aggregate.id,)
        or plan.output != sort.id
    ):
        raise ValueError("Unsupported sorted aggregation operation order")
    if set(sort.parameters) not in ({"metric", "direction"}, {"dimension", "direction"}):
        raise ValueError("Sort requires one governed target and explicit direction")
    direction = sort.parameters["direction"]
    if type(direction) is not str or direction not in ("ASC", "DESC"):
        raise ValueError("Unsupported sort direction")
    kind = "metric" if "metric" in sort.parameters else "dimension"
    name = sort.parameters[kind]
    if type(name) is not str or not name.strip():
        raise ValueError("Invalid governed sort reference")
    if len(bound.references) != 3:
        raise ValueError("Sorted aggregation requires exactly three governed references")
    matches = [
        ref for ref in bound.references
        if ref.step_id == sort.id and ref.parameter == kind and ref.kind == kind
    ]
    if len(matches) != 1 or matches[0].name.casefold() != name.casefold():
        raise ValueError("Governed sort reference mismatch")
    owner_step = aggregate if kind == "metric" else group
    owners = [
        ref for ref in bound.references
        if ref.step_id == owner_step.id and ref.parameter == kind and ref.kind == kind
    ]
    if len(owners) != 1 or owners[0].name.casefold() != name.casefold():
        raise ValueError("Sort target must match existing grouped output")
    # Reuse the validated grouped compiler instead of duplicating its
    # entity, physical-source and aggregation safety checks.
    base_plan = AnalyticalPlan(
        sources=plan.sources, steps=(group, aggregate), output=aggregate.id,
    )
    base_bound = BoundAnalyticalPlan(
        plan=base_plan,
        references=tuple(ref for ref in bound.references if ref.step_id != sort.id),
    )
    base_physical = replace(
        physical_plan,
        bound_plan=base_bound,
        dimensions=tuple(d for d in physical_plan.dimensions if d.step_id != sort.id),
        metrics=tuple(m for m in physical_plan.metrics if m.step_id != sort.id),
    )
    compiled = compile_analytical_grouped_aggregation(
        base_physical, metric_source=metric_source,
    )
    return CompiledAnalyticalQuery(
        sql=compiled.sql + f' ORDER BY "{ "value" if kind == "metric" else "dimension" }" {direction}'
    )


def compile_analytical_grouped_limit(
    physical_plan: UnifiedPhysicalAnalyticalPlan,
    *,
    metric_source: GovernedMetricSource,
    max_rows: int = 1000,
) -> CompiledAnalyticalQuery:
    """Compile GROUP -> AGGREGATE -> SORT -> LIMIT with a bounded row count.

    The preceding sorted plan is recompiled and validated; no arbitrary SQL
    or unordered limit is accepted. Row caps do not replace execution policy.
    """
    from dataclasses import replace

    from datapilot.application.services.analytical_plan import AnalyticalPlan
    from datapilot.application.services.analytical_plan_binding import BoundAnalyticalPlan

    if not isinstance(physical_plan, UnifiedPhysicalAnalyticalPlan):
        raise ValueError("Unified governed physical plan is required")
    if type(max_rows) is not int or max_rows < 1:
        raise ValueError("Invalid governed maximum row count")
    bound = physical_plan.bound_plan
    plan = bound.plan
    if len(plan.sources) != 1 or len(plan.steps) != 4:
        raise ValueError("Unsupported limited aggregation graph")
    group, aggregate, sort, limit = plan.steps
    if (
        limit.operation is not AnalyticalOperation.LIMIT
        or limit.inputs != (sort.id,)
        or plan.output != limit.id
    ):
        raise ValueError("Unsupported analytical limit operation order")
    if set(limit.parameters) != {"count"}:
        raise ValueError("Limit requires exactly one count parameter")
    count = limit.parameters["count"]
    if type(count) is not int or not 1 <= count <= max_rows:
        raise ValueError("Limit count must be a positive bounded integer")
    if any(ref.step_id == limit.id for ref in bound.references):
        raise ValueError("Limit cannot introduce semantic references")
    if any(
        item.step_id == limit.id
        for item in (
            *physical_plan.dimensions,
            *physical_plan.metrics,
            *physical_plan.time_dimensions,
        )
    ):
        raise ValueError("Limit cannot introduce physical mappings")
    prefix = AnalyticalPlan(
        sources=plan.sources,
        steps=(group, aggregate, sort),
        output=sort.id,
    )
    prefix_bound = BoundAnalyticalPlan(
        plan=prefix,
        references=tuple(ref for ref in bound.references if ref.step_id != limit.id),
    )
    prefix_physical = replace(physical_plan, bound_plan=prefix_bound)
    compiled = compile_analytical_grouped_sort(
        prefix_physical, metric_source=metric_source,
    )
    return CompiledAnalyticalQuery(
        sql=compiled.sql + f" LIMIT {count}",
        dialect=compiled.dialect,
    )


def compile_analytical_filtered_grouped_limit(
    physical_plan: UnifiedPhysicalAnalyticalPlan,
    *,
    metric_source: GovernedMetricSource,
    published_dimensions: tuple,
    max_rows: int = 1000,
) -> CompiledAnalyticalQuery:
    """Compile FILTER -> GROUP -> AGGREGATE -> SORT -> LIMIT, fail closed.

    Filter values must already be resolved against governed category mappings.
    SQL placeholders and parameter values remain separate until execution.
    """
    from dataclasses import replace

    from datapilot.application.services.analytical_plan import AnalyticalPlan
    from datapilot.application.services.analytical_plan_binding import BoundAnalyticalPlan
    from datapilot.application.services.analytical_filter_compiler import (
        compile_governed_dimension_filter,
    )

    if not isinstance(physical_plan, UnifiedPhysicalAnalyticalPlan):
        raise ValueError("Unified governed physical plan is required")
    bound = physical_plan.bound_plan
    plan = bound.plan
    if len(plan.sources) != 1 or len(plan.steps) != 5:
        raise ValueError("Unsupported filtered aggregation graph")
    filter_step, group, aggregate, sort, limit = plan.steps
    if (
        filter_step.operation is not AnalyticalOperation.FILTER
        or filter_step.inputs != plan.sources
        or group.inputs != (filter_step.id,)
        or aggregate.inputs != (group.id,)
        or sort.inputs != (aggregate.id,)
        or limit.inputs != (sort.id,)
        or plan.output != limit.id
    ):
        raise ValueError("Unsupported filter operation order")
    if set(filter_step.parameters) != {"dimension", "operator", "values"}:
        raise ValueError("Filter requires dimension, operator and values")
    refs = [
        ref for ref in bound.references if ref.step_id == filter_step.id
    ]
    if len(refs) != 1 or (
        refs[0].parameter, refs[0].kind
    ) != ("dimension", "dimension"):
        raise ValueError("Missing governed filter reference")
    filter_bindings = [
        d for d in physical_plan.dimensions if d.step_id == filter_step.id
    ]
    if len(filter_bindings) != 1 or filter_bindings[0].parameter != "dimension":
        raise ValueError("Missing governed physical filter dimension")
    if any(m.step_id == filter_step.id for m in physical_plan.metrics) or any(
        t.step_id == filter_step.id for t in physical_plan.time_dimensions
    ):
        raise ValueError("Unexpected physical filter mappings")
    mapping = filter_bindings[0]
    if refs[0].name != mapping.semantic_name:
        raise ValueError("Filter semantic reference mismatch")
    predicate = compile_governed_dimension_filter(
        dimension_name=refs[0].name,
        operator=filter_step.parameters["operator"],
        values=filter_step.parameters["values"],
        published_dimensions=published_dimensions,
    )
    if (
        predicate.entity_id != mapping.entity_id
        or predicate.schema_name != mapping.schema_name
        or predicate.table_name != mapping.table_name
        or predicate.entity_id != metric_source.entity_id
        or predicate.schema_name != metric_source.schema_name
        or predicate.table_name != metric_source.table_name
    ):
        raise ValueError("Filter physical source mismatch")
    # Restore the original input edge for the already-validated grouped
    # compiler; all downstream edges and their semantic bindings are retained.
    restored_group = replace(group, inputs=plan.sources)
    prefix_plan = AnalyticalPlan(
        sources=plan.sources,
        steps=(restored_group, aggregate, sort, limit),
        output=limit.id,
    )
    prefix_bound = BoundAnalyticalPlan(
        plan=prefix_plan,
        references=tuple(ref for ref in bound.references if ref.step_id != filter_step.id),
    )
    prefix_physical = replace(
        physical_plan,
        bound_plan=prefix_bound,
        dimensions=tuple(d for d in physical_plan.dimensions if d.step_id != filter_step.id),
    )
    compiled = compile_analytical_grouped_limit(
        prefix_physical, metric_source=metric_source, max_rows=max_rows,
    )
    marker = " GROUP BY "
    if compiled.sql.count(marker) != 1:
        raise ValueError("Expected grouped SQL structure")
    before, after = compiled.sql.split(marker)
    return CompiledAnalyticalQuery(
        sql=before + " WHERE " + predicate.sql + marker + after,
        dialect=compiled.dialect,
        parameters=predicate.parameters,
    )


def compile_analytical_grouped_having(
    physical_plan: UnifiedPhysicalAnalyticalPlan,
    *,
    metric_source: GovernedMetricSource,
    max_rows: int = 1000,
) -> CompiledAnalyticalQuery:
    """Compile GROUP -> AGGREGATE -> THRESHOLD -> SORT -> LIMIT.

    A threshold is restricted to the existing approved aggregate metric.
    Numeric values are passed separately as DB parameters; no arbitrary
    expressions, additional metrics or joins are supported.
    """
    import math
    from dataclasses import replace

    from datapilot.application.services.analytical_plan import AnalyticalPlan
    from datapilot.application.services.analytical_plan_binding import BoundAnalyticalPlan

    if not isinstance(physical_plan, UnifiedPhysicalAnalyticalPlan):
        raise ValueError("Unified governed physical plan is required")
    bound = physical_plan.bound_plan
    plan = bound.plan
    if len(plan.sources) != 1 or len(plan.steps) != 5:
        raise ValueError("Unsupported HAVING analytical graph")
    group, aggregate, threshold, sort, limit = plan.steps
    if (
        group.operation is not AnalyticalOperation.GROUP
        or aggregate.operation is not AnalyticalOperation.AGGREGATE
        or threshold.operation is not AnalyticalOperation.THRESHOLD
        or sort.operation is not AnalyticalOperation.SORT
        or limit.operation is not AnalyticalOperation.LIMIT
        or group.inputs != plan.sources
        or aggregate.inputs != (group.id,)
        or threshold.inputs != (aggregate.id,)
        or sort.inputs != (threshold.id,)
        or limit.inputs != (sort.id,)
        or plan.output != limit.id
    ):
        raise ValueError("Unsupported HAVING operation order")
    if set(threshold.parameters) != {"metric", "operator", "value"}:
        raise ValueError("HAVING requires metric, operator and value")
    op = threshold.parameters["operator"]
    operators = {"GT": ">", "GTE": ">=", "LT": "<", "LTE": "<=", "EQ": "="}
    if type(op) is not str or op not in operators:
        raise ValueError("Unsupported HAVING comparison operator")
    value = threshold.parameters["value"]
    if type(value) not in (int, float) or (
        type(value) is float and not math.isfinite(value)
    ):
        raise ValueError("HAVING requires a finite numeric threshold")
    refs = [
        ref for ref in bound.references if ref.step_id == threshold.id
    ]
    metrics = [
        metric for metric in physical_plan.metrics if metric.step_id == threshold.id
    ]
    if len(refs) != 1 or len(metrics) != 1:
        raise ValueError("HAVING requires one governed metric binding")
    ref = refs[0]
    metric = metrics[0]
    if (
        (ref.parameter, ref.kind) != ("metric", "metric")
        or (metric.parameter, metric.semantic_name) != ("metric", ref.name)
        or ref.name.casefold() != str(threshold.parameters["metric"]).casefold()
    ):
        raise ValueError("HAVING governed metric mismatch")
    aggregate_metrics = [
        m for m in physical_plan.metrics if m.step_id == aggregate.id
    ]
    if len(aggregate_metrics) != 1 or (
        metric.semantic_name != aggregate_metrics[0].semantic_name
        or metric.entity_id != aggregate_metrics[0].entity_id
        or metric.attribute_name != aggregate_metrics[0].attribute_name
        or metric.aggregation != aggregate_metrics[0].aggregation
        or metric.calculation_expression != aggregate_metrics[0].calculation_expression
    ):
        raise ValueError("HAVING must target the existing aggregated metric")
    if any(
        item.step_id == threshold.id
        for item in (*physical_plan.dimensions, *physical_plan.time_dimensions)
    ):
        raise ValueError("Unexpected HAVING physical mappings")
    restored_sort = replace(sort, inputs=(aggregate.id,))
    base_plan = AnalyticalPlan(
        sources=plan.sources,
        steps=(group, aggregate, restored_sort, limit),
        output=limit.id,
    )
    base_bound = BoundAnalyticalPlan(
        plan=base_plan,
        references=tuple(ref for ref in bound.references if ref.step_id != threshold.id),
    )
    base_physical = replace(
        physical_plan,
        bound_plan=base_bound,
        metrics=tuple(m for m in physical_plan.metrics if m.step_id != threshold.id),
    )
    compiled = compile_analytical_grouped_limit(
        base_physical, metric_source=metric_source, max_rows=max_rows,
    )
    marker = " ORDER BY "
    if compiled.sql.count(marker) != 1:
        raise ValueError("Expected governed ORDER BY structure")
    before, after = compiled.sql.split(marker)
    aggregate_metric = aggregate_metrics[0]
    column = _quote_identifier(metric_source.column_name)
    expression = f"{aggregate_metric.aggregation}({column})"
    return CompiledAnalyticalQuery(
        sql=before + f" HAVING {expression} {operators[op]} %s" + marker + after,
        dialect=compiled.dialect,
        parameters=compiled.parameters + (value,),
    )
