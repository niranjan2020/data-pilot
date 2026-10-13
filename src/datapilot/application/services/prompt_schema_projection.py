"""Least-privilege physical schema supplied to an LLM for governed metrics.

The full discovered schema remains available to SQL validation and identifier binding.
This projection is only activated when a governed metric and authoritative
published dimension catalog are present; it never confers publication rights.
"""
from __future__ import annotations

from datapilot.domain.models import SchemaMetadata


def project_metric_prompt_schema(
    schema: SchemaMetadata,
    governed_context: dict,
    *,
    authoritative_dimensions: bool,
) -> SchemaMetadata:
    if not authoritative_dimensions or not governed_context.get("metrics"):
        return schema

    entities = governed_context.get("entities") or []
    entity_by_id = {e.get("id"): e for e in entities}
    allowed: dict[tuple[str, str], set[str]] = {}

    def permit(entity, column):
        if not entity or not isinstance(column, str) or not column:
            return
        key = (str(entity.get("schema_name") or "").casefold(),
               str(entity.get("table_name") or "").casefold())
        allowed.setdefault(key, set()).add(column.casefold())

    for metric in governed_context["metrics"]:
        entity = entity_by_id.get(metric.get("entity_id"))
        permit(entity, entity.get("key_column") if entity else None)
        # Configured attributes on the metric's own entity remain available
        # for single-entity analytics. Other entities still require explicit
        # dimension publication and an approved relationship.
        if entity:
            for attribute in entity.get("attributes") or []:
                permit(entity, attribute.get("column_name"))
        attribute_name = metric.get("attribute_name")
        if entity and attribute_name:
            for attribute in entity.get("attributes") or []:
                if str(attribute.get("name") or "").casefold() == str(attribute_name).casefold():
                    permit(entity, attribute.get("column_name"))

    for dimension in governed_context.get("published_dimensions") or []:
        permit(entity_by_id.get(dimension.get("entity_id")), dimension.get("column_name"))

    for edge in governed_context.get("relationships") or []:
        permit(entity_by_id.get(edge.get("from_entity_id")), edge.get("from_column"))
        permit(entity_by_id.get(edge.get("to_entity_id")), edge.get("to_column"))

    # Never leak unrelated physical tables or columns into the prompt.
    tables = []
    for table in schema.tables:
        key = (str(table.schema_name or "").casefold(), table.name.casefold())
        columns = allowed.get(key, set())
        if columns:
            tables.append(table.model_copy(update={
                "columns": [col for col in table.columns if col.name.casefold() in columns],
                "primary_keys": [col for col in table.primary_keys if col.casefold() in columns],
                "foreign_keys": [
                    fk for fk in table.foreign_keys
                    if fk.constrained_column.casefold() in columns
                ],
                "unique_constraints": [
                    constraint for constraint in table.unique_constraints
                    if all(col.casefold() in columns for col in constraint.columns)
                ],
            }))
    return schema.model_copy(update={"tables": tables})
