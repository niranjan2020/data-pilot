"""Application service coordinating semantic matching, SQL generation, safety and execution."""

from __future__ import annotations

import re

from typing import Any, Dict, Optional

from datapilot.application.services.entity_resolver import DeterministicEntityResolver
from datapilot.application.services.context_budget import ContextBudgeter
from datapilot.application.services.semantic_context import SemanticContextAssembler
from datapilot.application.services.time_semantics import resolve_time_semantics
from datapilot.application.services.result_presentation import plan_result_presentation
from datapilot.application.services.result_summary import summarize_result
from datapilot.application.services.query_correctness import assess_query_correctness, sqlglot_dialect
from datapilot.application.services.semantic_intent_contract import SemanticIntentContract, resolve_published_comparison_cohorts
from datapilot.application.services.categorical_intent import is_unquoted_connective_code, resolve_categorical_intent
from datapilot.application.services.sql_correction import classify_sql_correction
from datapilot.application.services.execution_recovery import classify_execution_error
from datapilot.application.services.query_explanation import build_query_explanation
from datapilot.core.exceptions import DatabaseExecutionError, SemanticRetrievalError, SQLValidationError, TimeInterpretationError
from datapilot.core.logging import get_logger
from datapilot.domain.interfaces.database import DatabaseProvider
from datapilot.domain.interfaces.entity_resolver import EntityResolver
from datapilot.domain.interfaces.query_policy import QueryPolicyEnforcer
from datapilot.domain.interfaces.semantic import SemanticCatalogProvider
from datapilot.domain.interfaces.semantic_retriever import SemanticRetriever
from datapilot.domain.interfaces.sql_generator import SQLGenerator
from datapilot.domain.interfaces.sql_binder import SQLIdentifierBinder
from datapilot.domain.interfaces.sql_validator import SQLValidator
from datapilot.domain.models import SchemaMetadata
from datapilot.domain.policies import QueryExecutionPolicy
from datapilot.domain.query import ClarificationOption, ClarificationRequest, QueryRejection, QueryRequest, QueryResponse, QueryTrace
from datapilot.domain.semantic import QueryIntent, SemanticCatalog
from datapilot.infrastructure.sql.query_policy import SQLQueryPolicyEnforcer


logger = get_logger("datapilot.query")


def _invalid_qualified_columns(statement: Any) -> list[Any]:
    """Find unresolved qualified columns in their lexical SQL scopes.

    CTEs and nested SELECTs have separate namespaces; correlated subqueries
    can reference outer aliases. No database-specific identifiers are used.
    """
    from sqlglot import exp
    from sqlglot.optimizer.scope import traverse_scope

    scopes = list(traverse_scope(statement))
    invalid = []
    for scope in scopes:
        visible = set()
        current = scope
        while current is not None:
            visible.update(str(name).casefold() for name in current.sources)
            current = current.parent
        for column in scope.columns:
            if column.table and column.table.casefold() not in visible:
                invalid.append(column)
    if not scopes:
        visible = {
            str(table.alias_or_name).casefold()
            for table in statement.find_all(exp.Table)
            if table.alias_or_name
        }
        invalid = [
            column for column in statement.find_all(exp.Column)
            if column.table and column.table.casefold() not in visible
        ]
    return invalid



def _repaired_sql_scope_safe(sql: str, *, dialect: str, allowed_tables: Any) -> bool:
    """Reapply alias and physical-dataset constraints after SQL repair."""
    try:
        from sqlglot import exp, parse_one
        tree = parse_one(sql, read=sqlglot_dialect(dialect))
        if tree is None or _invalid_qualified_columns(tree):
            return False
        if allowed_tables is not None:
            physical = {
                f"{table.db}.{table.name}".casefold()
                for table in tree.find_all(exp.Table)
                if table.db and table.name
            }
            if not physical or physical - allowed_tables:
                return False
        return True
    except Exception:
        return False


class QueryOrchestrator:
    """Execute the core query workflow independently of any LLM vendor."""

    def __init__(
        self,
        database_provider: DatabaseProvider,
        sql_validator: SQLValidator,
        sql_generator: SQLGenerator,
        semantic_catalog_provider: SemanticCatalogProvider,
        *,
        entity_resolver: Optional[EntityResolver] = None,
        query_policy_enforcer: Optional[QueryPolicyEnforcer] = None,
        query_policy: Optional[QueryExecutionPolicy] = None,
        query_timeout_seconds: Optional[float] = None,
        semantic_retriever: Optional[SemanticRetriever] = None,
        semantic_retrieval_limit: int = 8,
        semantic_context_assembler: Optional[SemanticContextAssembler] = None,
        sql_identifier_binder: Optional[SQLIdentifierBinder] = None,
        context_budget_chars: int = 24000,
        relationship_publication_metadata: Any = None,
    ) -> None:
        self._database = database_provider
        self._relationship_publication_metadata = relationship_publication_metadata
        self._validator = sql_validator
        self._sql_generator = sql_generator
        self._semantic_catalog_provider = semantic_catalog_provider
        self._semantic_retriever = semantic_retriever
        self._semantic_retrieval_limit = semantic_retrieval_limit
        self._semantic_context_assembler = semantic_context_assembler
        self._sql_identifier_binder = sql_identifier_binder
        self._context_budgeter = ContextBudgeter(context_budget_chars)
        self._entity_resolver = entity_resolver or DeterministicEntityResolver()
        self._query_policy = query_policy or QueryExecutionPolicy()
        if query_timeout_seconds is not None:
            # Reconstruct through normal Pydantic validation rather than
            # model_copy(update=...), which does not validate updates by default.
            # Invalid runtime timeout configuration must fail closed at
            # composition time instead of entering the execution path.
            self._query_policy = QueryExecutionPolicy.model_validate({
                **self._query_policy.model_dump(),
                "timeout_seconds": query_timeout_seconds,
            })
        self._query_policy_enforcer = query_policy_enforcer or SQLQueryPolicyEnforcer()

    def _bind_identifiers(self, sql: str, schema: SchemaMetadata) -> str:
        """Bind physical identifiers through the configured dialect-aware port."""
        if self._sql_identifier_binder is None:
            return sql
        return self._sql_identifier_binder.bind(sql, schema, self._database.dialect)

    @staticmethod
    def _with_explanation(response: QueryResponse) -> QueryResponse:
        """Attach deterministic explainability once at each response boundary."""
        response.explanation = build_query_explanation(response)
        return response

    async def query(
        self,
        request: QueryRequest,
        *,
        schema: Optional[SchemaMetadata] = None,
        catalog: Optional[SemanticCatalog] = None,
        conversation_context: Optional[dict[str, Any]] = None,
    ) -> QueryResponse:
        """Resolve, generate, validate and execute one natural-language query."""
        conversation_context = dict(conversation_context or {})
        inherited_clarifications = dict(conversation_context.get("clarification_selections") or {})
        effective_clarifications = {**inherited_clarifications, **request.clarification_selections}
        contextual_question = self._contextualize_follow_up(
            request.question, conversation_context
        )
        retrieved_context: list[dict[str, Any]] = []
        if self._semantic_retriever is not None and request.source_name:
            try:
                # Stage 1 discovers the relevant physical/business neighborhood rather
                # than allowing rules/metrics to crowd datasets out of a flat top-k.
                search_kinds = getattr(self._semantic_retriever, "search_kinds", None)
                if search_kinds is not None:
                    seed_limit = max(4, min(self._semantic_retrieval_limit, 6))
                    structural_seeds = await search_kinds(
                        request.source_name, contextual_question,
                        ["dataset", "entity"], seed_limit,
                    )
                    # Stage 2 retrieves semantic intent objects independently. They do
                    # not select physical datasets; the authoritative catalog later
                    # constrains them to the Stage-1 dataset/entity neighborhood.
                    intent_seeds = await search_kinds(
                        request.source_name, contextual_question,
                        ["metric", "business_rule"], seed_limit,
                    )
                    retrieved_context = [*structural_seeds, *intent_seeds]
                else:
                    retrieved_context = await self._semantic_retriever.search(
                        request.source_name, contextual_question, self._semantic_retrieval_limit
                    )
            except Exception as exc:
                raise SemanticRetrievalError(
                    "Semantic retrieval failed",
                    details={"source_name": request.source_name},
                ) from exc

        logger.info(
            "query question=%r source=%r retrieval_stage=hierarchical_seeds retrieved=%s",
            request.question, request.source_name,
            [(x.get("kind"), x.get("name"), x.get("score")) for x in retrieved_context],
        )
        governed_context: dict[str, Any] = {}
        if self._semantic_context_assembler is not None and request.source_name:
            governed_context = await self._semantic_context_assembler.assemble(
                request.source_name, retrieved_context, contextual_question
            )
            if conversation_context:
                governed_context = await self._semantic_context_assembler.carry_forward(
                    request.source_name, governed_context, conversation_context
                )
            logger.info(
                "query governed_context datasets=%s entities=%s relationships=%s metrics=%s rules=%s",
                [f"{x['schema_name']}.{x['table_name']}" for x in governed_context.get("datasets", [])],
                [x["name"] for x in governed_context.get("entities", [])],
                [x["name"] for x in governed_context.get("relationships", [])],
                [x["name"] for x in governed_context.get("metrics", [])],
                [x["name"] for x in governed_context.get("business_rules", [])],
            )
        allowed_tables = getattr(self, "_onboarding_allowed_tables", None)
        if allowed_tables is not None:
            # First-run schema discovery is not semantic approval. In particular,
            # counts/sums/averages need a reviewed metric rather than an LLM
            # guess based on primary keys or column names.
            aggregate_intent = bool(re.search(
                r"\b(how many|count|number of|total|average|avg|sum|revenue|percentage|percent|rate)\b",
                contextual_question, flags=re.IGNORECASE,
            ))
            if aggregate_intent and not governed_context.get("metrics"):
                raise SQLValidationError(
                    "A governed metric is required for this business question",
                    details={"checks": [{
                        "code": "semantic_metric_not_configured",
                        "status": "failed",
                        "severity": "error",
                        "message": (
                            "No approved metric was resolved for this question. "
                            "Configure and publish the business metric in Admin Studio "
                            "before treating an aggregate as a governed answer."
                        ),
                    }]},
                )

            if not allowed_tables:
                raise SQLValidationError("No datasets are selected for querying")
            # Selected onboarding tables are the physical query boundary even
            # when the semantic index is empty or contains legacy candidates.
            selected_schemas = sorted({name.split(".", 1)[0] for name in allowed_tables})
            selected_discoveries = [
                await self._database.introspect_schema(schema_name)
                for schema_name in selected_schemas
            ]
            selected_physical = [
                table for discovery in selected_discoveries
                for table in discovery.tables
                if f"{table.schema_name}.{table.name}".lower() in allowed_tables
            ]
            if not selected_physical:
                raise SQLValidationError("Selected datasets are unavailable in the active datasource")
            schema = selected_discoveries[0].model_copy(update={"tables": selected_physical})
            governed_context["datasets"] = [
                item for item in governed_context.get("datasets", [])
                if f"{item.get('schema_name')}.{item.get('table_name')}".lower() in allowed_tables
            ]
            governed_context["entities"] = [
                item for item in governed_context.get("entities", [])
                if f"{item.get('schema_name')}.{item.get('table_name')}".lower() in allowed_tables
            ]
        else:
            schema = schema or await self._load_relevant_schema(
                retrieved_context, governed_context, contextual_question
            )
        logger.info(
            "query physical_schema tables=%s",
            [f"{t.schema_name}.{t.name}" for t in schema.tables],
        )
        governed_dataset_names = {
            f"{x['schema_name']}.{x['table_name']}"
            for x in governed_context.get("datasets", [])
        }
        governed_entity_names = {x["name"] for x in governed_context.get("entities", [])}
        governed_metric_names = {x["name"] for x in governed_context.get("metrics", [])}
        governed_rule_names = {x["name"] for x in governed_context.get("business_rules", [])}
        retrieval_diagnostics: list[dict[str, Any]] = []
        for candidate in retrieved_context:
            item = dict(candidate)
            kind = str(item.get("kind") or "")
            name = str(item.get("name") or "")
            metadata = item.get("metadata") or {}
            dataset_name = (
                f"{metadata.get('schema_name')}.{metadata.get('table_name')}"
                if metadata.get("schema_name") and metadata.get("table_name")
                else name
            )
            selected = (
                (kind == "dataset" and dataset_name in governed_dataset_names)
                or (kind == "entity" and name in governed_entity_names)
                or (kind == "metric" and name in governed_metric_names)
                or (kind == "business_rule" and name in governed_rule_names)
            )
            item["decision"] = "selected" if selected else "rejected"
            item["decision_reason"] = (
                "Included in governed semantic context"
                if selected
                else "Retrieved by vector search but excluded by semantic governance"
            )
            retrieval_diagnostics.append(item)

        trace = QueryTrace(
            retrieved_candidates=retrieval_diagnostics,
            governed_datasets=[
                f"{x['schema_name']}.{x['table_name']}"
                for x in governed_context.get("datasets", [])
            ],
            governed_entities=[x["name"] for x in governed_context.get("entities", [])],
            governed_relationships=[x["name"] for x in governed_context.get("relationships", [])],
            governed_metrics=[x["name"] for x in governed_context.get("metrics", [])],
            governed_business_rules=[x["name"] for x in governed_context.get("business_rules", [])],
            governed_time_dimensions=[x["name"] for x in governed_context.get("time_dimensions", [])],
            physical_tables=[f"{t.schema_name}.{t.name}" for t in schema.tables],
            physical_columns={
                f"{t.schema_name}.{t.name}": [column.name for column in t.columns]
                for t in schema.tables
            },
            conversation_context=conversation_context,
            clarification_selections=effective_clarifications,
            resource_budget=self._query_policy.resource_budget(),
        )
        catalog = catalog or await self._semantic_catalog_provider.get_catalog()

        # Explicit clarification selections are user-supplied governed identifiers.
        # Validate them before generic unsupported-question detection so an invalid
        # selection receives its precise deterministic rejection contract.
        selected_metric = effective_clarifications.get("metric")
        governed_metrics = governed_context.get("metrics", [])
        if selected_metric and not any(
            str(metric.get("name") or "").casefold() == selected_metric.casefold()
            for metric in governed_metrics
        ):
            return self._with_explanation(QueryResponse(
                question=request.question,
                status="rejected",
                trace=trace,
                rejection=QueryRejection(
                    code="invalid_metric_selection",
                    reason=f"The selected metric {selected_metric!r} is not present in the governed semantic context.",
                ),
                message=(
                    f"The selected metric {selected_metric!r} is not present in the "
                    "governed semantic context. No SQL was generated."
                ),
            ))

        selected_attribute = effective_clarifications.get("attribute")
        if selected_attribute:
            governed_attribute_values = {
                f"{entity.get('name')}.{attribute.get('name')}".casefold()
                for entity in governed_context.get("entities", [])
                for attribute in entity.get("attributes", [])
            }
            if selected_attribute.casefold() not in governed_attribute_values:
                return self._with_explanation(QueryResponse(
                    question=request.question,
                    status="rejected",
                    trace=trace,
                    rejection=QueryRejection(
                        code="invalid_attribute_selection",
                        reason=f"The selected attribute {selected_attribute!r} is not present in the governed semantic context.",
                    ),
                    message=(
                        f"The selected attribute {selected_attribute!r} is not present in the "
                        "governed semantic context. No SQL was generated."
                    ),
                ))

        selected_time_dimension = effective_clarifications.get("time_dimension")
        if selected_time_dimension and not any(
            str(dimension.get("name") or "").casefold() == selected_time_dimension.casefold()
            for dimension in governed_context.get("time_dimensions", [])
        ):
            return self._with_explanation(QueryResponse(
                question=request.question,
                status="rejected",
                trace=trace,
                rejection=QueryRejection(
                    code="invalid_time_dimension_selection",
                    reason=(
                        f"The selected time dimension {selected_time_dimension!r} "
                        "is not present in the governed semantic context."
                    ),
                ),
                message=(
                    f"The selected time dimension {selected_time_dimension!r} is not present "
                    "in the governed semantic context. No SQL was generated."
                ),
            ))

        resolver_catalog = catalog
        selected_entity = effective_clarifications.get("entity")
        if selected_entity:
            selected_entities = [
                entity for entity in catalog.entities
                if entity.name.casefold() == selected_entity.casefold()
            ]
            if not selected_entities:
                return self._with_explanation(QueryResponse(
                    question=request.question,
                    status="rejected",
                    trace=trace,
                    rejection=QueryRejection(
                        code="invalid_entity_selection",
                        reason=f"The selected entity {selected_entity!r} is not present in the governed semantic catalog.",
                    ),
                    message=(
                        f"The selected entity {selected_entity!r} is not present in the "
                        "governed semantic catalog. No SQL was generated."
                    ),
                ))
            resolver_catalog = catalog.model_copy(update={"entities": selected_entities})

        intent = self._entity_resolver.resolve(contextual_question, resolver_catalog, schema)
        if (
            catalog.entities
            and intent.entity is None
            and not intent.ambiguities
        ):
            return self._with_explanation(QueryResponse(
                question=request.question,
                status="rejected",
                confidence=intent.confidence,
                resolved_intent=intent,
                trace=trace,
                rejection=QueryRejection(
                    code="unsupported_question",
                    reason=(
                        "The question could not be mapped to any governed business "
                        "entity in the semantic catalog."
                    ),
                ),
                message=(
                    "I could not map this question to a governed business entity. "
                    "No SQL was generated."
                ),
            ))
        if intent.ambiguities:
            entity_by_name = {entity.name: entity for entity in catalog.entities}
            options = [
                ClarificationOption(
                    value=name,
                    label=name,
                    description=entity_by_name[name].description if name in entity_by_name else None,
                )
                for name in intent.ambiguities
            ]
            return self._with_explanation(QueryResponse(
                question=request.question,
                status="ambiguous",
                confidence=intent.confidence,
                semantic_ambiguities=intent.ambiguities,
                clarification=ClarificationRequest(
                    kind="entity",
                    key="entity",
                    question="Which business entity do you mean?",
                    options=options,
                ),
                resolved_intent=intent,
                trace=trace,
                message="I found more than one governed entity that could match this question.",
            ))

        selected_metric = effective_clarifications.get("metric")
        governed_metrics = governed_context.get("metrics", [])
        if selected_metric:
            selected_metrics = [
                metric for metric in governed_metrics
                if str(metric.get("name") or "").casefold() == selected_metric.casefold()
            ]
            if not selected_metrics:
                return self._with_explanation(QueryResponse(
                    question=request.question,
                    status="rejected",
                    confidence=intent.confidence,
                    resolved_intent=intent,
                    trace=trace,
                    rejection=QueryRejection(
                        code="invalid_metric_selection",
                        reason=f"The selected metric {selected_metric!r} is not present in the governed semantic context.",
                    ),
                    message=(
                        f"The selected metric {selected_metric!r} is not present in the "
                        "governed semantic context. No SQL was generated."
                    ),
                ))
            governed_metrics = selected_metrics
            governed_context["metrics"] = governed_metrics
            trace.governed_metrics = [str(metric.get("name") or "") for metric in governed_metrics]
        else:
            metric_matches = self._explicit_metric_matches(contextual_question, governed_metrics)
            ambiguous_group = next(
                (group for group in metric_matches.values() if len(group) > 1),
                None,
            )
            if ambiguous_group:
                return self._with_explanation(QueryResponse(
                    question=request.question,
                    status="ambiguous",
                    confidence=intent.confidence,
                    semantic_ambiguities=[
                        "Metric reference matches multiple governed metrics: "
                        + ", ".join(metric["name"] for metric in ambiguous_group)
                    ],
                    clarification=ClarificationRequest(
                        kind="metric",
                        key="metric",
                        question="Which governed metric do you mean?",
                        options=[
                            ClarificationOption(
                                value=str(metric["name"]),
                                label=str(metric["name"]),
                                description=str(metric.get("description") or "") or None,
                            )
                            for metric in ambiguous_group
                        ],
                    ),
                    resolved_intent=intent,
                    trace=trace,
                    message="The metric wording matches more than one governed business metric.",
                ))

            # Multiple distinct explicit metric references are composition, not
            # ambiguity. For example, "revenue and units sold" intentionally asks
            # for both governed metrics. Restrict generation to those explicit
            # metrics so unrelated vector candidates cannot leak into the query.
            explicit_metrics: list[dict[str, Any]] = []
            seen_metric_names: set[str] = set()
            for group in metric_matches.values():
                for metric in group:
                    metric_name = str(metric.get("name") or "")
                    if metric_name.casefold() not in seen_metric_names:
                        explicit_metrics.append(metric)
                        seen_metric_names.add(metric_name.casefold())
            if explicit_metrics:
                governed_context["metrics"] = explicit_metrics
                trace.governed_metrics = [
                    str(metric.get("name") or "") for metric in explicit_metrics
                ]

        selected_attribute = effective_clarifications.get("attribute")
        attribute_candidates = self._ambiguous_attribute_matches(
            contextual_question, governed_context.get("entities", [])
        )
        if selected_attribute:
            selected = next(
                (
                    candidate for candidate in attribute_candidates
                    if candidate["value"].casefold() == selected_attribute.casefold()
                ),
                None,
            )
            if selected is None:
                for entity in governed_context.get("entities", []):
                    for attribute in entity.get("attributes", []):
                        value = f"{entity.get('name')}.{attribute.get('name')}"
                        if value.casefold() == selected_attribute.casefold():
                            selected = {
                                "value": value,
                                "label": value,
                                "entity": str(entity.get("name") or ""),
                                "attribute": str(attribute.get("name") or ""),
                                "column_name": str(attribute.get("column_name") or ""),
                                "description": attribute.get("description"),
                            }
                            break
                    if selected is not None:
                        break
            if selected is None:
                return self._with_explanation(QueryResponse(
                    question=request.question,
                    status="rejected",
                    confidence=intent.confidence,
                    resolved_intent=intent,
                    trace=trace,
                    rejection=QueryRejection(
                        code="invalid_attribute_selection",
                        reason=f"The selected attribute {selected_attribute!r} is not present in the governed semantic context.",
                    ),
                    message=(
                        f"The selected attribute {selected_attribute!r} is not present in the "
                        "governed semantic context. No SQL was generated."
                    ),
                ))
            governed_context["resolved_attribute_selection"] = selected
        elif len(attribute_candidates) > 1:
            return self._with_explanation(QueryResponse(
                question=request.question,
                status="ambiguous",
                confidence=intent.confidence,
                semantic_ambiguities=[
                    "Attribute/filter reference matches multiple governed attributes: "
                    + ", ".join(candidate["label"] for candidate in attribute_candidates)
                ],
                clarification=ClarificationRequest(
                    kind="attribute",
                    key="attribute",
                    question="Which governed attribute should this filter use?",
                    options=[
                        ClarificationOption(
                            value=candidate["value"],
                            label=candidate["label"],
                            description=candidate.get("description"),
                        )
                        for candidate in attribute_candidates
                    ],
                ),
                resolved_intent=intent,
                trace=trace,
                message="The filter wording can refer to more than one governed attribute.",
            ))

        governed_filters = self._required_filters(
            contextual_question,
            governed_context.get("entities", []),
            intent.filters,
            schema=schema,
        )
        governed_grouping_columns = self._required_grouping_columns(
            contextual_question,
            governed_context.get("entities", []),
            selected_attribute=governed_context.get("resolved_attribute_selection"),
            metrics=governed_context.get("metrics", []),
            schema=schema,
        )
        if governed_filters:
            governed_context["resolved_filters"] = governed_filters
        if governed_grouping_columns:
            governed_context["required_grouping_columns"] = governed_grouping_columns

        parameters = self._merge_resolved_parameters(request.parameters, intent)
        trace.resolved_parameters = parameters
        governed_time_dimensions = governed_context.get("time_dimensions", [])
        selected_time_dimension = effective_clarifications.get("time_dimension")
        if selected_time_dimension:
            governed_time_dimensions = [
                dimension for dimension in governed_time_dimensions
                if str(dimension.get("name") or "").casefold() == selected_time_dimension.casefold()
            ]
            if not governed_time_dimensions:
                return self._with_explanation(QueryResponse(
                    question=request.question,
                    status="rejected",
                    confidence=intent.confidence,
                    resolved_intent=intent,
                    trace=trace,
                    rejection=QueryRejection(
                        code="invalid_time_dimension_selection",
                        reason=(
                            f"The selected time dimension {selected_time_dimension!r} "
                            "is not present in the governed semantic context."
                        ),
                    ),
                    message=(
                        f"The selected time dimension {selected_time_dimension!r} is not present "
                        "in the governed semantic context. No SQL was generated."
                    ),
                ))
        try:
            time_interpretation = resolve_time_semantics(
                contextual_question, governed_time_dimensions
            )
        except Exception as exc:
            raise TimeInterpretationError(
                "Governed time interpretation failed",
                details={
                    "time_dimensions": [
                        str(dimension.get("name") or "")
                        for dimension in governed_time_dimensions
                    ],
                },
            ) from exc
        if time_interpretation:
            trace.time_interpretation = time_interpretation
            if time_interpretation.get("status") == "ambiguous":
                return self._with_explanation(QueryResponse(
                    question=request.question,
                    status="ambiguous",
                    confidence=intent.confidence,
                    semantic_ambiguities=[
                        "Time reference matches multiple governed time dimensions: "
                        + ", ".join(time_interpretation.get("candidates", []))
                    ],
                    clarification=ClarificationRequest(
                        kind="time_dimension",
                        key="time_dimension",
                        question="Which governed date/time role should be used?",
                        options=[
                            ClarificationOption(value=name, label=name)
                            for name in time_interpretation.get("candidates", [])
                        ],
                    ),
                    resolved_intent=intent,
                    trace=trace,
                    message="The time reference matches more than one governed date/time role.",
                ))
            governed_context["resolved_time_filter"] = time_interpretation
        semantic_contract = SemanticIntentContract.from_governed_context(
            governed_context,
            grouping_columns=governed_grouping_columns,
            required_filters=governed_filters,
            required_relationships=self._required_relationships(governed_context),
            time_plan=time_interpretation,
            comparison_cohorts=resolve_published_comparison_cohorts(
                contextual_question,
                governed_context.get("entities", []),
                selected_attribute=governed_context.get("resolved_attribute_selection"),
            ) or [
                {"column_name": item["column_name"], "values": item["values"]}
                for item in governed_filters
                if str(item.get("operator", "")).upper() == "IN"
                and isinstance(item.get("values"), (list, tuple))
                and len(item["values"]) >= 2
            ],
            aggregation_grain=governed_grouping_columns,
        )
        generation_context = {
            "semantic_intent_contract": semantic_contract.as_dict(),
            "governed_semantic_context": governed_context,
            "retrieved_semantic_context": retrieved_context,
            "semantic_catalog": catalog.model_dump(mode="json"),
            "query_intent": intent.model_dump(mode="json"),
            "parameters": parameters,
            "clarification_selections": effective_clarifications,
            "conversation_context": conversation_context,
        }
        generation_context, budget = self._context_budgeter.apply(generation_context)
        logger.info("query context_budget=%s", budget)
        trace.context_budget = budget
        build_messages = getattr(self._sql_generator, "build_messages", None)
        if callable(build_messages):
            diagnostic_messages = build_messages(
                question=request.question,
                schema=schema,
                context=generation_context,
                dialect=self._database.dialect,
            )
            trace.llm_messages = [
                {"role": message.role, "content": message.content}
                for message in diagnostic_messages
            ]
        generated = await self._sql_generator.generate(
            question=request.question,
            schema=schema,
            context=generation_context,
            dialect=self._database.dialect,
        )
        logger.info("query generated_sql=%s", generated)
        trace.generated_sql = generated
        bound_sql = self._bind_identifiers(generated, schema)
        # Governed metadata, not question keywords, determines eligible text columns.
        # Never normalize canonical code mappings or non-text attributes.
        from datapilot.application.services.named_text_filter import (
            normalize_governed_text_filters,
        )
        if self._database.dialect in ("postgres", "postgresql"):
            bound_sql = normalize_governed_text_filters(
                bound_sql,
                governed_entities=governed_context.get("entities", []),
                physical_schema=schema,
                dialect="postgres",
            )
        trace.bound_sql = bound_sql
        logger.info("query catalog_bound_sql=%s", bound_sql)
        validation_args = {
            "question": request.question,
            "source": "generator",
            "confidence": intent.confidence,
            "resolved_intent": intent,
            "retrieved_context": retrieved_context,
            "trace": trace,
            "execute": not request.dry_run,
            "governed_tables": trace.physical_tables,
            "governed_metrics": list(semantic_contract.metrics),
            "required_grouping_columns": list(semantic_contract.dimensions),
            "required_filters": list(semantic_contract.filters),
            "governed_entities": governed_context.get("entities", []),
            "selected_categorical_attribute": semantic_contract.categorical_attribute,
            "required_relationships": list(semantic_contract.relationships),
            "required_time_plan": semantic_contract.time_plan,
            "comparison_cohorts": list(semantic_contract.comparison_cohorts),
            "aggregation_grain": list(semantic_contract.aggregation_grain),
            "data_source_name": request.source_name,
        }
        async def recover_execution_error(
            sql: str,
            exc: DatabaseExecutionError,
        ) -> QueryResponse:
            classify_provider_error = getattr(
                self._database, "classify_execution_error", None
            )
            evidence = (
                classify_provider_error(dict(exc.details or {}))
                if callable(classify_provider_error)
                else None
            )
            decision = classify_execution_error(evidence=evidence)
            if not decision.recoverable:
                raise exc

            recovery_context = dict(generation_context)
            recovery_context["execution_recovery"] = {
                "attempt": 1,
                "max_attempts": 1,
                "failed_sql": sql,
                "database_error": dict(exc.details or {}),
                "classification": {
                    "recoverable": decision.recoverable,
                    "category": decision.category,
                    "reason": decision.reason,
                    "provider": decision.provider,
                    "code": decision.code,
                    "sqlstate": decision.sqlstate,
                },
            }
            corrected = await self._sql_generator.generate(
                question=request.question,
                schema=schema,
                context=recovery_context,
                dialect=self._database.dialect,
            )
            corrected_bound_sql = self._bind_identifiers(corrected, schema)
            trace.execution_recovery_attempts.append({
                **recovery_context["execution_recovery"],
                "corrected_sql": corrected,
                "corrected_bound_sql": corrected_bound_sql,
            })
            logger.info(
                "query execution_recovery_attempt=1 corrected_sql=%s",
                corrected_bound_sql,
            )
            # B2 owns this regenerated proposal. Any validation/correctness/policy
            # or database failure here is terminal; it cannot re-enter B1 or B2.
            return await self._validate_and_execute(
                sql=corrected_bound_sql,
                **validation_args,
            )

        try:
            return await self._validate_and_execute(sql=bound_sql, **validation_args)
        except DatabaseExecutionError as exc:
            return await recover_execution_error(bound_sql, exc)
        except SQLValidationError as exc:
            checks = tuple((exc.details or {}).get("checks") or ())
            decision = classify_sql_correction(correctness_checks=checks)
            if not decision.recoverable:
                raise

            correction_context = dict(generation_context)
            correction_context["sql_correction"] = {
                "attempt": 1,
                "max_attempts": 1,
                "failed_sql": bound_sql,
                "category": decision.category,
                "feedback": list(decision.feedback),
            }
            corrected = await self._sql_generator.generate(
                question=request.question,
                schema=schema,
                context=correction_context,
                dialect=self._database.dialect,
            )
            corrected_bound_sql = self._bind_identifiers(corrected, schema)
            trace.correction_attempts.append({
                "attempt": 1,
                "failed_sql": bound_sql,
                "category": decision.category,
                "feedback": list(decision.feedback),
                "corrected_sql": corrected,
                "corrected_bound_sql": corrected_bound_sql,
            })
            logger.info(
                "query correction_attempt=1 corrected_sql=%s",
                corrected_bound_sql,
            )
            # B1 owns this regenerated proposal. Its validation failure is terminal.
            # A database execution failure may independently enter B2 exactly once.
            try:
                return await self._validate_and_execute(
                    sql=corrected_bound_sql,
                    **validation_args,
                )
            except DatabaseExecutionError as execution_exc:
                return await recover_execution_error(
                    corrected_bound_sql,
                    execution_exc,
                )

    async def _validate_and_execute(
        self,
        *,
        question: str,
        sql: str,
        source: str,
        confidence: float,
        resolved_intent: Optional[QueryIntent] = None,
        retrieved_context: Optional[list[dict[str, Any]]] = None,
        trace: Optional[QueryTrace] = None,
        execute: bool = True,
        governed_tables: Optional[list[str]] = None,
        governed_metrics: Optional[list[dict[str, Any]]] = None,
        required_grouping_columns: Optional[list[str]] = None,
        required_filters: Optional[list[dict[str, Any]]] = None,
        governed_entities: Optional[list[dict[str, Any]]] = None,
        selected_categorical_attribute: Optional[dict[str, Any]] = None,
        required_relationships: Optional[list[dict[str, Any]]] = None,
        required_time_plan: Optional[dict[str, Any]] = None,
        comparison_cohorts: Optional[list[dict[str, Any]]] = None,
        aggregation_grain: Optional[list[str]] = None,
        data_source_name: Optional[str] = None,
    ) -> QueryResponse:
        validation = await self._validator.validate(
            sql,
            dialect=self._database.dialect,
            enforce_read_only=True,
        )
        if not validation.is_valid:
            raise SQLValidationError(
                "Generated SQL failed safety validation",
                details={"errors": validation.errors},
            )

        # A persisted onboarding selection is a hard execution boundary.
        # Reject unselected physical tables even when SQL is syntactically valid.
        allowed_tables = getattr(self, "_onboarding_allowed_tables", None)
        if allowed_tables is not None:
            # Validator diagnostics may include quoted identifiers and aliases.
            # Resolve actual physical tables from the validated SQL AST instead.
            import sqlglot
            from sqlglot import exp
            try:
                statements = sqlglot.parse(validation.sanitized_sql or sql, read=sqlglot_dialect(self._database.dialect))
                if len(statements) != 1 or statements[0] is None:
                    raise ValueError("Expected one SQL statement")
                actual_tables = {
                    f"{table.db}.{table.name}".casefold()
                    for table in statements[0].find_all(exp.Table)
                    if table.db and table.name
                }
                # CTE references are query-local relations, not physical
                # datasets. Keep rejecting every other unqualified table.
                from sqlglot.optimizer.scope import traverse_scope
                unqualified = set()
                for scope in traverse_scope(statements[0]):
                    for _alias, (node, resolved_source) in scope.selected_sources.items():
                        if isinstance(node, exp.Table) and not node.db:
                            if isinstance(resolved_source, exp.Table):
                                unqualified.add(node.name)
                    selected_nodes = {id(node) for node, _ in scope.selected_sources.values()}
                    for node in scope.tables:
                        if not node.db and id(node) not in selected_nodes:
                            unqualified.add(node.name)
            except Exception as exc:
                raise SQLValidationError(
                    "Unable to verify selected datasets in generated SQL",
                    details={"checks": [{"code": "dataset_selection_violation",
                                         "status": "failed", "severity": "error",
                                         "message": "SQL table-reference verification failed."}]},
                ) from exc
            # A schema name is not a valid column qualifier. Qualifiers must
            # resolve to a table alias or physical table name in the statement.
            # Reject the LLM's astra."id" when FROM astra.vessels.
            physical_tables = list(statements[0].find_all(exp.Table))
            invalid_columns = _invalid_qualified_columns(statements[0])
            # The generator sometimes uses the schema as a column qualifier:
            # astra."id" FROM astra.vessels. This is repairable only for a
            # single physical table in the same schema, with no other tables
            # or nested scopes that could change column ownership.
            repaired_sql = None
            if invalid_columns and len(physical_tables) == 1 and not any(
                isinstance(node, (exp.Subquery, exp.CTE, exp.Join, exp.Union))
                for node in statements[0].walk()
            ):
                only_table = physical_tables[0]
                if only_table.db and all(
                    column.table.casefold() == only_table.db.casefold()
                    and not column.db and not column.catalog
                    for column in invalid_columns
                ):
                    for column in invalid_columns:
                        column.set("table", exp.to_identifier(only_table.alias_or_name))
                    repaired_sql = statements[0].sql(dialect="postgres")
                    # Never execute a rewrite without passing the same safety
                    # validator again. The original validator result is stale.
                    repaired_validation = await self._validator.validate(
                        repaired_sql, dialect=self._database.dialect,
                        enforce_read_only=True,
                    )
                    if not repaired_validation.is_valid:
                        repaired_sql = None
                    else:
                        validation = repaired_validation
                        validation.sanitized_sql = repaired_sql
            if invalid_columns and repaired_sql is None:
                raise SQLValidationError(
                    "Generated SQL contains an invalid column qualifier",
                    details={"checks": [{
                        "code": "sql_identifier_qualifier_violation",
                        "status": "failed", "severity": "error",
                        "message": "Unknown table aliases or column qualifiers: "
                                   + ", ".join(sorted({c.table for c in invalid_columns})),
                    }]},
                )
            unauthorized = sorted(actual_tables - allowed_tables)
            if not allowed_tables or unauthorized or unqualified:
                raise SQLValidationError(
                    "Generated SQL references a dataset outside the onboarded selection",
                    details={"checks": [{
                        "code": "dataset_selection_violation",
                        "status": "failed",
                        "severity": "error",
                        "message": "Query references unselected or unqualified datasets: "
                                   + ", ".join(unauthorized + sorted(unqualified) or ["no datasets selected"]),
                    }]},
                )

        executable_sql = validation.sanitized_sql or sql
        if trace is not None:
            trace.validated_sql = executable_sql
            trace.validation_affected_tables = list(validation.affected_tables)
            trace.validation_warnings = list(validation.warnings)
        logger.info(
            "query validated_sql=%s affected_tables=%s warnings=%s",
            executable_sql, validation.affected_tables, validation.warnings,
        )

        # Production queries must not bypass governance by omitting relationship
        # contracts. Parse the validated SQL, including nested SELECTs, and
        # require an authoritative publication for every physical JOIN.
        trusted_published_relationships = None
        publication_metadata = getattr(self, "_relationship_publication_metadata", None)
        if publication_metadata is not None:
            import sqlglot
            from sqlglot import exp
            from datapilot.application.published_join_authorization import authorize_published_joins

            try:
                statements = sqlglot.parse(executable_sql, read="postgres")
                has_join = any(isinstance(node, exp.Join)
                               for statement in statements if statement is not None
                               for node in statement.walk())
            except Exception as exc:
                raise SQLValidationError(
                    "Cannot verify SQL relationship publication",
                    details={"checks": [{
                        "code": "relationship_publication_violation",
                        "status": "failed", "severity": "error",
                        "message": "Unable to parse SQL for relationship authorization.",
                    }]},
                ) from exc

            if has_join or required_relationships:
                source_id = (await publication_metadata.get_data_source_id(data_source_name)
                             if data_source_name else None)
                authorization = await authorize_published_joins(
                    publication_metadata, source_id, executable_sql,
                    required_relationships or [],
                )
                if not authorization.allowed:
                    raise SQLValidationError(
                        "Generated SQL uses an unpublished or invalid relationship",
                        details={"checks": [{
                            "code": "relationship_publication_violation",
                            "status": "failed", "severity": "error",
                            "message": "; ".join(authorization.reasons),
                        }]},
                    )
                # Reuse the exact grants checked against the SQL AST.
                trusted_published_relationships = list(authorization.verified_grants)

        try:
            self._validate_nonempty_array_filters(question, executable_sql, governed_entities or [])
        except SQLValidationError as nonempty_error:
            repaired_sql = self._repair_nonempty_array_filter(executable_sql, nonempty_error)
            if repaired_sql is None:
                raise
            repaired_validation = await self._validator.validate(
                repaired_sql, dialect=self._database.dialect, enforce_read_only=True,
            )
            if not repaired_validation.is_valid:
                raise nonempty_error
            candidate_sql = repaired_validation.sanitized_sql or repaired_sql
            self._validate_nonempty_array_filters(
                question, candidate_sql, governed_entities or [],
            )
            executable_sql = candidate_sql
            validation = repaired_validation
        try:
            self._validate_canonical_array_literals(question, executable_sql, governed_entities or [])
        except SQLValidationError as array_error:
            repaired_sql = self._repair_canonical_array_literal(executable_sql, array_error)
            if repaired_sql is None:
                raise
            repaired_validation = await self._validator.validate(
                repaired_sql, dialect=self._database.dialect, enforce_read_only=True,
            )
            if not repaired_validation.is_valid:
                raise array_error
            candidate_sql = repaired_validation.sanitized_sql or repaired_sql
            self._validate_canonical_array_literals(
                question, candidate_sql, governed_entities or [],
            )
            executable_sql = candidate_sql
            validation = repaired_validation

        # Enforce resolved published categorical values for both single-value
        # requests and explicit comparisons. Grouping by a categorical column
        # alone does not constrain the requested categories.
        try:
            self._validate_explicit_categorical_comparison(
                question, executable_sql, governed_entities or [],
                selected_attribute=selected_categorical_attribute,
                dialect=self._database.dialect,
            )
        except SQLValidationError as comparison_error:
            repaired_sql = self._repair_explicit_categorical_comparison(
                executable_sql, comparison_error, dialect=self._database.dialect,
            )
            if repaired_sql is None:
                raise
            repaired_validation = await self._validator.validate(
                repaired_sql, dialect=self._database.dialect,
                enforce_read_only=True,
            )
            if not repaired_validation.is_valid:
                raise comparison_error
            executable_sql = repaired_validation.sanitized_sql or repaired_sql
            validation = repaired_validation
            self._validate_explicit_categorical_comparison(
                question, executable_sql, governed_entities or [],
                selected_attribute=selected_categorical_attribute,
                dialect=self._database.dialect,
            )

        correctness_checks = assess_query_correctness(
            affected_tables=validation.affected_tables,
            governed_tables=governed_tables or [],
            sql=executable_sql,
            question=question,
            governed_metrics=governed_metrics or [],
            required_grouping_columns=required_grouping_columns or [],
            required_filters=required_filters or [],
            required_relationships=required_relationships or [],
            required_time_plan=required_time_plan,
            comparison_cohorts=comparison_cohorts or [],
            aggregation_grain=aggregation_grain or [],
            trusted_published_relationships=trusted_published_relationships,
            dialect=self._database.dialect,
        )
        if trace is not None:
            trace.correctness_checks = correctness_checks
        failed_correctness = [
            check for check in correctness_checks if check.get("status") == "failed"
        ]
        unavailable_required_codes = {
            "metric_expression_verification_unavailable",
            "grouping_verification_unavailable",
            "filter_verification_unavailable",
            "relationship_verification_unavailable",
            "time_verification_unavailable",
        }
        unavailable_required = [
            check
            for check in correctness_checks
            if check.get("status") == "skipped"
            and check.get("code") in unavailable_required_codes
        ]
        blocking_correctness = [*failed_correctness, *unavailable_required]
        if blocking_correctness:
            from datapilot.application.services.comparison_group_repair import repair_missing_comparison_groups
            from datapilot.application.services.ranking_grain_repair import repair_ranking_grain
            from datapilot.application.services.array_expansion_repair import repair_grouped_array_expansion
            candidate = repair_grouped_array_expansion(
                executable_sql, correctness_checks, dialect=self._database.dialect,
            )
            if candidate is None:
                candidate = repair_ranking_grain(
                    executable_sql, correctness_checks, dialect=self._database.dialect,
                )
            if candidate is None:
                candidate = repair_missing_comparison_groups(
                    executable_sql, correctness_checks, dialect=self._database.dialect,
                )
            if candidate is None and len(blocking_correctness) == 1:
                candidate = self._repair_missing_governed_filter(
                    executable_sql, blocking_correctness, dialect=self._database.dialect,
                )
            if candidate is None:
                logger.warning('comparison_group_repair no_candidate failed_codes=%s', [c.get('code') for c in blocking_correctness])
            if candidate is not None:
                logger.info('comparison_group_repair validating_candidate')
                repaired_validation = await self._validator.validate(
                    candidate, dialect=self._database.dialect, enforce_read_only=True,
                )
                if not repaired_validation.is_valid:
                    logger.warning('comparison_group_repair candidate_validation_failed')
                if repaired_validation.is_valid and not _repaired_sql_scope_safe(
                    repaired_validation.sanitized_sql or candidate,
                    dialect=self._database.dialect,
                    allowed_tables=allowed_tables,
                ):
                    logger.warning("sql_repair_scope_validation_failed")
                elif repaired_validation.is_valid:
                    repaired_sql = repaired_validation.sanitized_sql or candidate
                    repaired_checks = assess_query_correctness(
                        affected_tables=repaired_validation.affected_tables,
                        governed_tables=governed_tables or [],
                        sql=repaired_sql,
                        question=question,
                        governed_metrics=governed_metrics or [],
                        required_grouping_columns=required_grouping_columns or [],
                        required_filters=required_filters or [],
                        required_relationships=required_relationships or [],
                        required_time_plan=required_time_plan,
                        comparison_cohorts=comparison_cohorts or [],
                        aggregation_grain=aggregation_grain or [],
                        trusted_published_relationships=trusted_published_relationships,
                        dialect=self._database.dialect,
                    )
                    if not any(c.get("status") == "failed" or (
                        c.get("status") == "skipped" and
                        c.get("code") in unavailable_required_codes
                    ) for c in repaired_checks):
                        logger.info('comparison_group_repair accepted')
                        executable_sql = repaired_sql
                        validation = repaired_validation
                        correctness_checks = repaired_checks
                        blocking_correctness = []
                        if trace is not None:
                            trace.correctness_checks = repaired_checks
                            trace.validated_sql = repaired_sql
        if blocking_correctness:
            logger.warning('comparison_group_repair rejected remaining_codes=%s', [c.get('code') for c in blocking_correctness])
            raise SQLValidationError(
                "Generated SQL failed governed correctness checks",
                details={"checks": blocking_correctness},
            )

        policy_result = self._query_policy_enforcer.enforce(
            executable_sql,
            self._database.dialect,
            self._query_policy,
        )
        if not policy_result.is_allowed:
            raise SQLValidationError(
                "SQL query failed execution policy",
                details={"errors": policy_result.errors},
            )

        if trace is not None:
            trace.policy_sql = policy_result.sql
            trace.policy_warnings = list(policy_result.warnings)
        logger.info(
            "query executable_sql=%s policy_warnings=%s",
            policy_result.sql, policy_result.warnings,
        )
        if not execute:
            if trace is not None:
                trace.execution = {"executed": False}
            return self._with_explanation(QueryResponse(
                question=question,
                status="dry_run",
                source=source,
                sql=policy_result.sql,
                result=None,
                confidence=confidence,
                resolved_intent=resolved_intent,
                retrieved_context=retrieved_context or [],
                validation_warnings=[*validation.warnings, *policy_result.warnings],
                trace=trace,
                message="Dry run completed. SQL was generated, bound, validated and policy-checked without execution.",
            ))

        result = await self._database.execute_query(
            policy_result.sql,
            timeout_seconds=self._query_policy.timeout_seconds,
        )
        logger.info(
            "query completed rows=%s execution_time_ms=%.2f",
            result.row_count, result.execution_time_ms,
        )
        if trace is not None:
            trace.execution = {
                "row_count": result.row_count,
                "execution_time_ms": result.execution_time_ms,
            }
        if result.row_count > self._query_policy.max_result_rows:
            raise SQLValidationError(
                "Query result exceeded the configured maximum row count",
                details={
                    "row_count": result.row_count,
                    "max_result_rows": self._query_policy.max_result_rows,
                    "sql": policy_result.sql,
                    "correctness_checks": correctness_checks,
                },
            )

        presentation = plan_result_presentation(
            question,
            result,
            trace.time_interpretation if trace is not None else None,
        )

        result_summary = summarize_result(question, result, presentation)

        return self._with_explanation(QueryResponse(
            question=question,
            status="completed",
            source=source,
            sql=policy_result.sql,
            result=result,
            confidence=confidence,
            resolved_intent=resolved_intent,
            retrieved_context=retrieved_context or [],
            validation_warnings=[*validation.warnings, *policy_result.warnings],
            trace=trace,
            presentation=presentation,
            result_summary=result_summary,
        ))

    async def _load_relevant_schema(
        self,
        retrieved_context: list[dict[str, Any]],
        governed_context: Optional[dict[str, Any]] = None,
        question: str = "",
    ) -> SchemaMetadata:
        """Introspect physical schemas, then prune tables and governed columns."""
        governed_entities = (governed_context or {}).get("entities", [])
        governed_datasets = (governed_context or {}).get("datasets", [])
        physical_tables = {
            (d.get("schema_name"), d.get("table_name"))
            for d in governed_datasets
            if d.get("schema_name") and d.get("table_name")
        }
        physical_tables.update({
            (e.get("schema_name"), e.get("table_name"))
            for e in governed_entities
            if e.get("schema_name") and e.get("table_name")
        })
        if not physical_tables:
            physical_tables = {
                (item.get("metadata", {}).get("schema_name"), item.get("metadata", {}).get("table_name"))
                for item in retrieved_context
                if item.get("kind") == "entity"
                and item.get("metadata", {}).get("schema_name")
                and item.get("metadata", {}).get("table_name")
            }
        if not physical_tables:
            return await self._database.introspect_schema()

        schema_names = sorted({schema for schema, _ in physical_tables})
        discovered = [await self._database.introspect_schema(name) for name in schema_names]
        tables = [
            table
            for item in discovered
            for table in item.tables
            if (table.schema_name or item.schema_name, table.name) in physical_tables
        ]

        # Governed column pruning. Required join/key/display/metric columns are
        # always retained. Explicitly mentioned semantic attributes are retained.
        # If an entity has no configured attributes, keep its full physical table
        # as a safe compatibility fallback rather than guessing.
        entities = governed_entities
        relationships = (governed_context or {}).get("relationships", [])
        metrics = (governed_context or {}).get("metrics", [])
        normalized_question = " " + __import__("re").sub(
            r"[^a-z0-9]+", " ", question.lower()
        ).strip() + " "
        required: dict[tuple[str, str], set[str]] = {}

        def require(schema_name: str | None, table_name: str | None, column: str | None) -> None:
            if schema_name and table_name and column:
                required.setdefault((schema_name, table_name), set()).add(column.lower())

        entity_by_id = {e["id"]: e for e in entities}
        for entity in entities:
            key = (entity.get("schema_name"), entity.get("table_name"))
            require(*key, entity.get("key_column"))
            require(*key, entity.get("display_column"))
            attributes = entity.get("attributes") or []
            # Configured semantic attributes are already governed/approved
            # columns. Keep them for selected entities so value-only language
            # such as "red products" can still generate a Color filter even when
            # the attribute name itself is not present in the question.
            for attribute in attributes:
                require(*key, attribute.get("column_name"))

        for relationship in relationships:
            left = entity_by_id.get(relationship.get("from_entity_id"))
            right = entity_by_id.get(relationship.get("to_entity_id"))
            if left:
                require(left.get("schema_name"), left.get("table_name"), relationship.get("from_column"))
            if right:
                require(right.get("schema_name"), right.get("table_name"), relationship.get("to_column"))

        for metric in metrics:
            owner = entity_by_id.get(metric.get("entity_id"))
            if owner:
                attribute = next(
                    (
                        a for a in (owner.get("attributes") or [])
                        if (a.get("name") or "").lower() == (metric.get("attribute_name") or "").lower()
                    ),
                    None,
                )
                if attribute:
                    require(owner.get("schema_name"), owner.get("table_name"), attribute.get("column_name"))

        pruned_tables = []
        for table in tables:
            table_key = (table.schema_name, table.name)
            entity = next(
                (
                    e for e in entities
                    if (e.get("schema_name"), e.get("table_name")) == table_key
                ),
                None,
            )
            # No semantic entity/attributes means we lack enough governance to
            # safely prune; preserve all columns.
            if entity is None or not (entity.get("attributes") or []):
                pruned_tables.append(table)
                continue
            keep = required.get(table_key, set())
            columns = [col for col in table.columns if col.name.lower() in keep]
            # Never produce an unusable empty table context.
            if not columns:
                columns = table.columns
            pruned_tables.append(table.model_copy(update={"columns": columns}))

        logger.info(
            "query column_context=%s",
            {
                f"{t.schema_name}.{t.name}": [c.name for c in t.columns]
                for t in pruned_tables
            },
        )
        return SchemaMetadata(schema_name=None, tables=pruned_tables, dialect=self._database.dialect)

    @staticmethod
    def _contextualize_follow_up(
        question: str,
        conversation_context: Dict[str, Any],
    ) -> str:
        """Create retrieval/resolution text for an explicit follow-up.

        The previous SQL is intentionally excluded. Only the prior natural-language
        question and governed semantic lineage are carried forward, so every turn
        still performs fresh retrieval, SQL generation, validation and policy checks.
        """
        previous_question = str(conversation_context.get("previous_question") or "").strip()
        analytical_turns = [
            str(turn).strip()
            for turn in (conversation_context.get("analytical_turns") or [])
            if str(turn).strip()
        ]
        if not analytical_turns and previous_question:
            analytical_turns = [previous_question]
        if not analytical_turns:
            return question

        metrics = ", ".join(conversation_context.get("governed_metrics") or [])
        entities = ", ".join(conversation_context.get("governed_entities") or [])
        semantic_hint = "; ".join(
            part for part in (
                f"prior metrics: {metrics}" if metrics else "",
                f"prior entities: {entities}" if entities else "",
            ) if part
        )
        suffix = f" ({semantic_hint})" if semantic_hint else ""
        lineage = " -> ".join(analytical_turns)
        return (
            f"Prior analytical turns: {lineage}{suffix}. "
            f"Current follow-up: {question}"
        )

    @staticmethod
    def _explicit_metric_matches(
        question: str, metrics: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Group explicit governed metric matches by the wording that matched.

        A single phrase mapping to multiple metrics is genuinely ambiguous
        (for example a shared synonym such as "sales"). Distinct phrases such
        as "revenue" and "units sold" are an intentional multi-metric request
        and must be composed rather than clarified.
        """
        normalized = " " + " ".join(
            re.findall(r"[a-z0-9]+", question.casefold())
        ) + " "
        matches: dict[str, list[dict[str, Any]]] = {}
        for metric in metrics:
            terms = [metric.get("name"), *(metric.get("synonyms") or [])]
            matched_terms: set[str] = set()
            for term in terms:
                if not term:
                    continue
                semantic_term = " ".join(re.findall(r"[a-z0-9]+", str(term).casefold()))
                if semantic_term and f" {semantic_term} " in normalized:
                    matched_terms.add(semantic_term)
            for semantic_term in matched_terms:
                matches.setdefault(semantic_term, []).append(metric)
        return matches

    @staticmethod
    def _ambiguous_attribute_matches(
        question: str, entities: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Find genuinely ambiguous governed attribute/filter references.

        Only governed entity attributes participate. Explicit attribute
        names/synonyms take precedence. For value-only location phrasing such
        as "in London", clarification is requested only when multiple governed
        location-like attributes could legally own that filter.
        """
        normalized = " " + " ".join(re.findall(r"[a-z0-9]+", question.casefold())) + " "
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(entity: dict[str, Any], attribute: dict[str, Any]) -> None:
            entity_name = str(entity.get("name") or "")
            attribute_name = str(attribute.get("name") or "")
            if not entity_name or not attribute_name:
                return
            value = f"{entity_name}.{attribute_name}"
            if value.casefold() in seen:
                return
            seen.add(value.casefold())
            candidates.append({
                "value": value,
                "label": f"{entity_name} · {attribute_name}",
                "entity": entity_name,
                "attribute": attribute_name,
                "column_name": attribute.get("column_name"),
                "description": attribute.get("description"),
            })

        for entity in entities:
            for attribute in entity.get("attributes") or []:
                terms = [attribute.get("name"), *(attribute.get("synonyms") or [])]
                if any(
                    (semantic_term := " ".join(re.findall(r"[a-z0-9]+", str(term).casefold())))
                    and f" {semantic_term} " in normalized
                    for term in terms if term
                ):
                    add(entity, attribute)

        # An explicit semantic attribute reference is stronger than a value
        # synonym. One named attribute resolves a shared-value ambiguity.
        if candidates:
            return candidates if len(candidates) > 1 else []

        # A published value synonym used for different columns on the same
        # entity needs clarification before SQL generation. Never treat a
        # one-character canonical code as conversational evidence.
        words = re.findall(r"[a-z0-9]+", question.casefold())
        for entity in entities:
            matched_phrases: dict[tuple[int, int], list[dict[str, Any]]] = {}
            for attribute in entity.get("attributes") or []:
                for mapping in attribute.get("value_mappings") or []:
                    for synonym in mapping.get("synonyms") or []:
                        phrase = re.findall(r"[a-z0-9]+", str(synonym).casefold())
                        if not phrase:
                            continue
                        for i in range(len(words) - len(phrase) + 1):
                            if words[i:i + len(phrase)] == phrase:
                                matched_phrases.setdefault((i, i + len(phrase)), []).append(attribute)
            for matched_attributes in matched_phrases.values():
                columns = {str(a.get("column_name") or "").casefold() for a in matched_attributes}
                if len(columns) > 1:
                    for attribute in matched_attributes:
                        add(entity, attribute)
        if candidates:
            return candidates if len(candidates) > 1 else []

        if not re.search(r"\b(?:in|within)\s+[^\s]+", question, flags=re.IGNORECASE):
            return []

        location_terms = {"country", "region", "state", "city", "location"}
        for entity in entities:
            for attribute in entity.get("attributes") or []:
                terms = [attribute.get("name"), *(attribute.get("synonyms") or [])]
                tokens = {
                    token
                    for term in terms if term
                    for token in re.findall(r"[a-z0-9]+", str(term).casefold())
                }
                if tokens.intersection(location_terms):
                    add(entity, attribute)
        return candidates if len(candidates) > 1 else []

    @staticmethod
    def _validate_nonempty_array_filters(
        question: str, sql: str, entities: list[dict[str, Any]],
    ) -> None:
        """Fail closed when an explicitly requested populated array is tested only for NULL.

        Attribute names and array types come from published semantic metadata.
        This intentionally does not guess that domain words such as 'capable'
        imply nonempty array semantics.
        """
        import sqlglot
        from sqlglot import exp

        explicit_nonempty = bool(re.search(
            r"\b(?:non[- ]empty|not empty|populated|at least one)\b", question, re.I,
        ))
        # Opt-in governed vocabulary: only explicitly published phrases imply
        # nonempty semantics. No domain terms are inferred from the question.
        if not explicit_nonempty and not any(
            attribute.get("nonempty_intent_phrases")
            for entity in entities for attribute in entity.get("attributes") or []
        ):
            return
        ast = sqlglot.parse_one(sql, read="postgres")
        for entity in entities:
            for attribute in entity.get("attributes") or []:
                data_type = str(attribute.get("data_type") or "").casefold()
                if not (data_type.endswith("[]") or "array" in data_type):
                    continue
                terms = [attribute.get("name"), *(attribute.get("synonyms") or [])]
                def phrase_present(term):
                    phrase = str(term or "").strip()
                    return bool(phrase) and bool(re.search(
                        r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", question, re.I,
                    ))
                explicitly_named = explicit_nonempty and any(phrase_present(term) for term in terms)
                governed_phrase = any(
                    phrase_present(term)
                    for term in attribute.get("nonempty_intent_phrases") or []
                )
                if not (explicitly_named or governed_phrase):
                    continue
                column_name = str(attribute.get("column_name") or "").casefold()
                for select in ast.find_all(exp.Select):
                    where = select.args.get("where")
                    # A missing WHERE cannot establish an explicitly requested
                    # nonempty array filter.
                    if where is None:
                        raise SQLValidationError(
                            'Generated SQL does not enforce nonempty array semantics',
                            details={'checks': [{
                                'code': 'nonempty_array_filter_violation',
                                'status': 'failed', 'severity': 'error',
                                'column_name': attribute.get('column_name'),
                                'message': 'Explicit nonempty intent requires a positive array population filter.',
                            }]},
                        )
                    # Restrict to positive AND conjuncts. An OR, negation, or
                    # nested query cannot establish the nonempty guarantee.
                    def conjuncts(node):
                        if isinstance(node, exp.Paren):
                            return conjuncts(node.this)
                        if isinstance(node, exp.And):
                            return conjuncts(node.this) + conjuncts(node.expression)
                        return [node]
                    clauses = conjuncts(where.this)
                    # SQLGlot may normalize IS NOT NULL as NOT(IS(...)) or
                    # another equivalent AST shape. Match the *individual*
                    # parsed conjunct's normalized SQL instead of its class.
                    column_pattern = r'(?:[A-Za-z_][A-Za-z_0-9]*\.)?"?' + re.escape(column_name) + r'"?'
                    null_only = any(
                        re.fullmatch(
                            rf'{column_pattern}\s+IS\s+NOT\s+NULL',
                            predicate.sql(dialect="postgres").strip(),
                            re.I,
                        )
                        for predicate in clauses
                    )
                    # Explicit nonempty intent requires proof even when the SQL
                    # omits IS NOT NULL entirely. A missing filter must not
                    # silently pass merely because there is no null check.
                    # Cardinality > 0, array_length > 0, or a positive
                    # element-membership predicate may establish population.
                    # Fail closed if the generated SQL uses only IS NOT NULL.
                    # A second reference to the array is not necessarily proof
                    # that it contains elements (e.g. labels = '{}' or
                    # CARDINALITY(labels) = 0). Accept only positive cardinality
                    # checks; other expressions require separate semantic proof.
                    # Only a standalone positive conjunct proves the filter.
                    # A substring match inside OR / NOT / a nested SELECT
                    # can incorrectly authorize empty arrays.
                    cardinality_pattern = (
                        rf'(?:CARDINALITY|ARRAY_LENGTH)\s*\(\s*{column_pattern}'
                        rf'(?:\s*,\s*1)?\s*\)\s*>\s*0'
                    )
                    positive_cardinality = any(
                        re.fullmatch(
                            cardinality_pattern, predicate.sql(dialect='postgres').strip(), re.I,
                        ) is not None
                        for predicate in clauses
                    )
                    if not positive_cardinality:
                        raise SQLValidationError(
                            "Generated SQL does not enforce nonempty array semantics",
                            details={"checks": [{
                                "code": "nonempty_array_filter_violation",
                                "status": "failed", "severity": "error",
                                "column_name": attribute.get("column_name"),
                                "message": "IS NOT NULL includes empty arrays; require a positive cardinality or governed membership condition.",
                            }]},
                        )

    @staticmethod
    def _repair_nonempty_array_filter(sql: str, error: SQLValidationError) -> Optional[str]:
        """Add a governed nonempty-array conjunct to a simple single-table SELECT.

        The metadata-derived column must be present in the physical SQL scope.
        Refuse joins, nested queries, set operations and complex WHERE expressions.
        """
        import sqlglot
        from sqlglot import exp

        checks = (getattr(error, "details", None) or {}).get("checks") or []
        matching = [item for item in checks if item.get("code") == "nonempty_array_filter_violation"]
        if len(matching) != 1:
            return None
        column_name = str(matching[0].get("column_name") or "")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", column_name):
            return None
        try:
            tree = sqlglot.parse_one(sql, read="postgres")
        except Exception:
            return None
        if not isinstance(tree, exp.Select) or any(
            isinstance(node, (exp.Join, exp.Subquery, exp.Union, exp.With, exp.Exists))
            for node in tree.walk()
        ):
            return None
        tables = list(tree.find_all(exp.Table))
        if len(tables) != 1:
            return None
        where = tree.args.get("where")
        if where is not None and any(
            isinstance(node, (exp.Or, exp.Not, exp.Subquery, exp.Select))
            for node in where.walk()
        ):
            return None
        # Only repair a column that is already referenced in the SELECT or WHERE.
        # Do not guess that a governed attribute belongs to an unrelated table.
        columns = list(tree.find_all(exp.Column))
        if not any(col.name.casefold() == column_name.casefold() for col in columns):
            return None
        table_alias = tables[0].alias_or_name
        if any(
            col.name.casefold() == column_name.casefold()
            and col.table and col.table.casefold() not in (table_alias.casefold(), tables[0].name.casefold())
            for col in columns
        ):
            return None
        column = exp.column(column_name, table=table_alias if any(
            col.table and col.name.casefold() == column_name.casefold() for col in columns
        ) else None)
        condition = exp.GT(
            this=exp.Anonymous(this="CARDINALITY", expressions=[column]),
            expression=exp.Literal.number(0),
        )
        if where is None:
            tree.set("where", exp.Where(this=condition))
        else:
            # Preserve all business filters; only eliminate exact redundant
            # non-null checks on the same governed array. CARDINALITY > 0
            # already excludes NULL, and other comparisons may be meaningful.
            def flatten_and(node):
                if isinstance(node, exp.Paren):
                    return flatten_and(node.this)
                if isinstance(node, exp.And):
                    return flatten_and(node.this) + flatten_and(node.expression)
                return [node]

            predicates = flatten_and(where.this)
            null_pattern = (
                rf'(?:[A-Za-z_][A-Za-z_0-9]*\.)?"?{re.escape(column_name)}"?'
                rf'\s+IS\s+NOT\s+NULL'
            )
            predicates = [
                predicate for predicate in predicates
                if not re.fullmatch(
                    null_pattern, predicate.sql(dialect="postgres").strip(), re.I,
                )
            ]
            predicates.append(condition)
            combined = predicates[0]
            for predicate in predicates[1:]:
                combined = exp.and_(combined, predicate)
            tree.set("where", exp.Where(this=combined))
        return tree.sql(dialect="postgres")

    @staticmethod
    def _repair_canonical_array_literal(sql: str, error: SQLValidationError) -> Optional[str]:
        """Repair one unambiguous case-only array literal mismatch, fail closed otherwise."""
        import sqlglot
        from sqlglot import exp

        checks = (getattr(error, "details", None) or {}).get("checks") or []
        check = next((item for item in checks if item.get("code") == "canonical_array_value_violation"), None)
        if not check or len(check.get("canonical_values") or []) != 1:
            return None
        canonical = str(check["canonical_values"][0])
        column = str(check.get("column_name") or "").casefold()
        if not column:
            return None
        try:
            tree = sqlglot.parse_one(sql, read="postgres")
        except Exception:
            return None
        if not isinstance(tree, exp.Select) or any(
            isinstance(node, (exp.Join, exp.Subquery, exp.Union, exp.With))
            for node in tree.walk()
        ):
            return None
        where = tree.args.get("where")
        if where is None or where.find(exp.Or) or where.find(exp.Not):
            return None
        # A single positive, direct array-containment filter is the only
        # permitted repair surface. Other predicates remain fail-closed.
        pattern = (
            r'(?P<column>(?:[A-Za-z_]\w*\.)?"?[A-Za-z_]\w*"?)'
            r"\s*@>\s*ARRAY\s*\[\s*'(?P<value>(?:''|[^'])*)'\s*\]"
        )
        matches = []
        for match in re.finditer(pattern, sql, re.I):
            if match.group("column").split(".")[-1].strip('"').casefold() != column:
                continue
            value = match.group("value").replace("''", "'")
            if value.casefold() == canonical.casefold() and value != canonical:
                matches.append(match)
        if len(matches) != 1:
            return None
        match = matches[0]
        # Ensure the matching predicate belongs to WHERE, not SELECT.
        if match.group(0) not in where.sql(dialect="postgres"):
            return None
        start, end = match.span("value")
        return sql[:start] + canonical.replace("'", "''") + sql[end:]

    @staticmethod
    def _validate_canonical_array_literals(
        question: str, sql: str, entities: list[dict[str, Any]],
    ) -> None:
        """Reject noncanonical string array literals for requested published values.

        The semantic mapping is authoritative; SQL literal matching for PostgreSQL
        array membership is case-sensitive. No business vocabulary is embedded.
        """
        import sqlglot
        from sqlglot import exp

        statement = sqlglot.parse_one(sql, read="postgres")
        question_words = re.findall(r"[a-z0-9]+", question.casefold())

        def mentions(term: str) -> bool:
            phrase = re.findall(r"[a-z0-9]+", str(term).casefold())
            return bool(phrase) and any(
                question_words[i:i + len(phrase)] == phrase
                for i in range(len(question_words) - len(phrase) + 1)
            )

        for entity in entities:
            table_name = str(entity.get("table_name") or "").casefold()
            schema_name = str(entity.get("schema_name") or "").casefold()
            if table_name and not any(
                table.name.casefold() == table_name
                and (not schema_name or (table.db or "").casefold() == schema_name)
                for table in statement.find_all(exp.Table)
            ):
                continue
            for attribute in entity.get("attributes") or []:
                data_type = str(attribute.get("data_type") or "").casefold()
                if not (data_type.endswith("[]") or "array" in data_type):
                    continue
                column_name = str(attribute.get("column_name") or "").casefold()
                if not column_name:
                    continue
                published = {}
                for mapping in attribute.get("value_mappings") or []:
                    canonical = str(mapping.get("canonical_value") or "")
                    if not canonical:
                        continue
                    if any(mentions(term) for term in [canonical, *(mapping.get("synonyms") or [])]):
                        published.setdefault(canonical.casefold(), set()).add(canonical)
                if not published:
                    continue
                observed = set()
                array_filter_seen = False
                for predicate in statement.find_all(exp.Expression):
                    # Only inspect expressions that actually compare this array
                    # column with an ARRAY[...] literal, not unrelated projections.
                    arrays = list(predicate.find_all(exp.Array))
                    if not arrays or not any(
                        isinstance(col, exp.Column) and col.name.casefold() == column_name
                        for col in predicate.find_all(exp.Column)
                    ):
                        continue
                    # Restrict to the smallest expression enclosing both array
                    # column and literal, so an outer SELECT does not accidentally
                    # mix unrelated predicates.
                    if any(
                        isinstance(child, exp.Expression)
                        and child is not predicate
                        and list(child.find_all(exp.Array))
                        and any(c.name.casefold() == column_name for c in child.find_all(exp.Column))
                        for child in predicate.iter_expressions()
                    ):
                        continue
                    array_filter_seen = True
                    for array in arrays:
                        for literal in array.expressions:
                            if not isinstance(literal, exp.Literal) or not literal.is_string:
                                continue
                            value = str(literal.this)
                            observed.add(value)
                            allowed = published.get(value.casefold())
                            if allowed and value not in allowed:
                                raise SQLValidationError(
                                    "Generated SQL uses a noncanonical governed array value",
                                    details={"checks": [{
                                        "code": "canonical_array_value_violation",
                                        "status": "failed", "severity": "error",
                                        "column_name": attribute.get("column_name"),
                                        "canonical_values": sorted(allowed),
                                        "message": "Array membership literal must match the exact published canonical value.",
                                    }]},
                                )
                # Only assert completeness when generated SQL already uses
                # literal-array filtering. A query that expands arrays with
                # UNNEST or groups by element requires a different grain-aware
                # validation contract.
                if array_filter_seen:
                    missing = sorted(
                        canonical for values in published.values()
                        for canonical in values if canonical not in observed
                    )
                    if missing:
                        raise SQLValidationError(
                            "Generated SQL omitted requested governed array categories",
                            details={"checks": [{
                                "code": "categorical_array_filter_violation",
                                "status": "failed", "severity": "error",
                                "column_name": attribute.get("column_name"),
                                "missing_canonical_values": missing,
                                "message": "Array filtering must include every requested published category.",
                            }]},
                        )

    @staticmethod
    def _validate_explicit_categorical_comparison(
        question: str, sql: str, entities: list[dict[str, Any]],
        selected_attribute: Optional[dict[str, Any]] = None,
        *, dialect: str = "postgresql",
    ) -> None:
        """Fail closed when two explicit, governed values are not SQL-filtered."""
        import sqlglot
        from sqlglot import exp

        def tokens(value: str) -> list[str]:
            return re.findall(r"[a-z0-9]+", value.casefold())

        def equivalent(left: str, right: str) -> bool:
            if left == right:
                return True
            # Generic inflection matching: "own" and "owned", "charter" and
            # "chartered". Never infer a canonical value without its mapping.
            return any(left + suffix == right or right + suffix == left
                       for suffix in ("ed", "s"))

        words = tokens(question)
        explicit_comparison = bool(re.search(r"\b(?:versus|vs\.?|between)\b", question, re.I))
        ast = sqlglot.parse_one(sql, read=sqlglot_dialect(dialect))
        outer_tables = [
            table for table in ast.find_all(exp.Table)
            if table.find_ancestor(exp.Select) is ast
        ] if isinstance(ast, exp.Select) else []
        for entity in entities:
            if selected_attribute and str(entity.get("name") or "").casefold() != str(
                selected_attribute.get("entity") or ""
            ).casefold():
                continue
            entity_table_name = str(entity.get("table_name") or "").casefold()
            # Only assess ambiguity for entities that could participate in
            # this query. Keep same-name/different-schema entities in scope
            # so the existing schema-binding rejection remains effective.
            if entity_table_name and not any(
                table.name.casefold() == entity_table_name for table in outer_tables
            ):
                continue
            # A phrase mapped to different columns on the same entity cannot
            # be assigned to either attribute without additional intent.
            # Restrict this check to published synonyms, not one-letter codes.
            phrase_columns = {}
            for attribute in entity.get("attributes") or []:
                column = str(attribute.get("column_name") or "").casefold()
                if selected_attribute and column != str(
                    selected_attribute.get("column_name") or ""
                ).casefold():
                    continue
                for mapping in attribute.get("value_mappings") or []:
                    for synonym in mapping.get("synonyms") or []:
                        phrase = tokens(str(synonym))
                        if not column or not phrase:
                            continue
                        for i in range(len(words) - len(phrase) + 1):
                            if all(equivalent(a, b) for a, b in zip(words[i:i + len(phrase)], phrase)):
                                phrase_columns.setdefault((i, i + len(phrase)), set()).add(column)
            conflicting = [
                columns for columns in phrase_columns.values() if len(columns) > 1
            ]
            # An explicit, unique governed attribute name resolves which
            # column owns a shared value synonym (e.g. "active operating
            # status"). Do not mistake it for value-level ambiguity.
            explicit_columns = set()
            for attribute in entity.get("attributes") or []:
                column = str(attribute.get("column_name") or "").casefold()
                for term in [attribute.get("name"), *(attribute.get("synonyms") or [])]:
                    phrase = tokens(str(term)) if term else []
                    if phrase and any(
                        all(equivalent(a, b) for a, b in zip(words[i:i + len(phrase)], phrase))
                        for i in range(len(words) - len(phrase) + 1)
                    ):
                        explicit_columns.add(column)
            if len(explicit_columns) == 1:
                conflicting = [
                    columns for columns in conflicting
                    if next(iter(explicit_columns)) not in columns
                ]
            if conflicting:
                raise SQLValidationError(
                    "Published categorical attribute is ambiguous",
                    details={"checks": [{
                        "code": "categorical_attribute_ambiguity",
                        "status": "failed", "severity": "error",
                        "message": "A categorical phrase matches multiple published attributes.",
                        "columns": sorted(set().union(*conflicting)),
                    }]},
                )
            for attribute in entity.get("attributes") or []:
                column_name = str(attribute.get("column_name") or "")
                if selected_attribute and column_name.casefold() != str(
                    selected_attribute.get("column_name") or ""
                ).casefold():
                    continue
                if len(explicit_columns) == 1 and column_name.casefold() not in explicit_columns:
                    continue
                mappings = attribute.get("value_mappings") or []
                if not column_name or not mappings:
                    continue
                # Categorical literal validation applies to categorical data,
                # not numeric/date range boundaries. Published numeric value
                # labels must not convert "between 2020 and 2021" into a
                # requirement for string equality/IN filters.
                data_type = str(attribute.get("data_type") or "").strip().casefold()
                numeric_or_temporal = (
                    data_type in {
                        "int", "int2", "int4", "int8", "integer", "bigint",
                        "smallint", "numeric", "decimal", "float", "float4",
                        "float8", "real", "double precision", "date",
                        "timestamp", "timestamptz", "timestamp without time zone",
                        "timestamp with time zone",
                    }
                    or data_type.startswith(("numeric(", "decimal(", "timestamp("))
                )
                if numeric_or_temporal:
                    continue
                # Resolve longest matching published phrases first, so a
                # composite label is not mistaken for its component synonyms.
                # Equal-length matches for different codes are ambiguous and
                # must never be silently selected.
                candidates = []
                for mapping in mappings:
                    canonical = str(mapping.get("canonical_value") or "")
                    for term in [canonical, *(mapping.get("synonyms") or [])]:
                        phrase = tokens(str(term))
                        if not canonical or not phrase:
                            continue
                        if is_unquoted_connective_code(question, str(term)):
                            continue
                        for i in range(len(words) - len(phrase) + 1):
                            if all(equivalent(a, b) for a, b in zip(words[i:i + len(phrase)], phrase)):
                                candidates.append((i, i + len(phrase), canonical))
                candidates.sort(key=lambda item: (-(item[1] - item[0]), item[0]))
                selected = []
                occupied = set()
                ambiguous = False
                for begin, end, canonical in candidates:
                    span = set(range(begin, end))
                    if span.intersection(occupied):
                        if any(
                            begin == s and end == e and canonical != code
                            for s, e, code in selected
                        ):
                            ambiguous = True
                        continue
                    selected.append((begin, end, canonical))
                    occupied.update(span)
                if ambiguous:
                    raise SQLValidationError(
                        "Published categorical mappings are ambiguous",
                        details={"checks": [{
                            "code": "categorical_mapping_ambiguity",
                            "status": "failed", "severity": "error",
                            "message": f"Multiple published values match the same phrase for {column_name}",
                        }]},
                    )
                matched = list(dict.fromkeys(code for _, _, code in selected))
                if not matched or (explicit_comparison and len(matched) < 2):
                    continue
                # Only a positive WHERE conjunction on the outer query can
                # guarantee a categorical restriction. Values in SELECT, JOIN,
                # HAVING, OR, NOT, or a nested SELECT are not sufficient.
                constrained = set()
                # Resolve column qualifiers against the outer query's physical
                # tables. An unrelated alias (or an ambiguous unqualified
                # column in a join) cannot establish a governed filter.
                outer_tables = [
                    table for table in ast.find_all(exp.Table)
                    if table.find_ancestor(exp.Select) is ast
                ] if isinstance(ast, exp.Select) else []
                # Match aliases to the governed entity's physical table.
                # Legacy entities without table identity retain the previous
                # conservative qualifier behavior.
                entity_table = str(entity.get("table_name") or "").casefold()
                entity_schema = str(entity.get("schema_name") or "").casefold()
                matching_tables = [
                    table for table in outer_tables
                    if (not entity_table or table.name.casefold() == entity_table)
                    and (not entity_schema or (table.db or "").casefold() == entity_schema)
                ]
                allowed_tables = matching_tables if entity_table else outer_tables
                # A selected semantic entity is not necessarily a SQL source:
                # vector retrieval may include related but unused entities.
                # Never impose its categorical mappings on an unrelated query.
                if entity_table and not matching_tables:
                    # A different physical table is unrelated retrieval context.
                    # The same table name in another schema is instead a failed
                    # governed binding: never silently accept that substitution.
                    same_name_tables = [
                        table for table in outer_tables
                        if table.name.casefold() == entity_table
                    ]
                    if not same_name_tables:
                        continue
                valid_qualifiers = {
                    (table.alias_or_name or "").casefold()
                    for table in allowed_tables
                }
                def correct_column(column):
                    if not isinstance(column, exp.Column) or column.name.casefold() != column_name.casefold():
                        return False
                    if column.table:
                        return column.table.casefold() in valid_qualifiers
                    return len(outer_tables) == 1 and len(allowed_tables) == 1

                where = ast.args.get("where")
                if isinstance(ast, exp.Select) and where:
                    def conjuncts(node):
                        if isinstance(node, exp.Paren):
                            return conjuncts(node.this)
                        if isinstance(node, exp.And):
                            return conjuncts(node.this) + conjuncts(node.expression)
                        return [node]

                    for predicate in conjuncts(where.this):
                        if isinstance(predicate, exp.Paren):
                            predicate = predicate.this
                        # PostgreSQL array membership is not scalar equality.
                        # Require the governed column and canonical string literals
                        # on a single positive outer WHERE conjunct. For multiple
                        # required values, only containment guarantees ALL values;
                        # overlap/ANY express ANY-of and cannot prove both.
                        if data_type.endswith("[]") or "array" in data_type:
                            # SQLGlot normalizes PostgreSQL operators into AST
                            # nodes; matching re-serialized SQL is unreliable.
                            def literal_values(node):
                                if isinstance(node, exp.Paren):
                                    return literal_values(node.this)
                                if isinstance(node, exp.Cast):
                                    return literal_values(node.this)
                                if isinstance(node, exp.Array):
                                    values = node.expressions
                                    if all(isinstance(v, exp.Literal) and v.is_string for v in values):
                                        return {str(v.this).casefold() for v in values}
                                if isinstance(node, exp.Literal) and node.is_string:
                                    return {str(node.this).casefold()}
                                return set()

                            kind = predicate.key.casefold()
                            lhs = predicate.this
                            rhs = predicate.expression
                            observed = set()
                            if kind in {"arraycontainsall", "arraycontains", "array_contains"} and correct_column(lhs):
                                observed = literal_values(rhs)
                            elif kind in {"arrayoverlaps", "array_overlaps"} and correct_column(lhs):
                                if len(matched) == 1:
                                    observed = literal_values(rhs)
                            elif isinstance(predicate, exp.EQ):
                                # 'LNG' = ANY(array_col) is single-value membership.
                                if len(matched) == 1:
                                    for value, any_node in ((lhs, rhs), (rhs, lhs)):
                                        if isinstance(any_node, exp.Any) and correct_column(any_node.this.this if isinstance(any_node.this, exp.Paren) else any_node.this):
                                            observed = literal_values(value)
                            if {v.casefold() for v in matched}.issubset(observed):
                                constrained.update(observed)
                            continue
                        if not isinstance(predicate, (exp.EQ, exp.In)):
                            continue
                        lhs = predicate.this
                        if not correct_column(lhs):
                            continue
                        values = ([predicate.expression] if isinstance(predicate, exp.EQ)
                                  else list(predicate.expressions))
                        # Do not union values across separate AND predicates:
                        # status='O' AND status='T' is contradictory, not a
                        # comparison covering both categories. A single IN
                        # predicate must cover the full requested value set.
                        predicate_values = {
                            str(v.this).casefold() for v in values
                            if isinstance(v, exp.Literal) and v.is_string
                        }
                        required_values = {v.casefold() for v in matched}
                        if required_values.issubset(predicate_values):
                            constrained.update(predicate_values)
                # A second AND constraint on the same column may silently
                # narrow the requested comparison (e.g. IN ('O','T') AND
                # status='O'). Reject rather than trusting the first IN.
                if constrained and where:
                    same_column_predicates = [
                        p for p in conjuncts(where.this)
                        if any(
                            correct_column(c) or c.name.casefold() == column_name.casefold()
                            for c in p.find_all(exp.Column)
                        )
                    ]
                    if len(same_column_predicates) != 1:
                        constrained.clear()
                # Distinct conditional aggregates can preserve comparison
                # cohorts without a global WHERE restriction. Each requested
                # canonical value must appear in its own aggregate's CASE,
                # associated with the governed column.
                if not constrained and len(matched) >= 2 and isinstance(ast, exp.Select):
                    covered = set()
                    for aggregate in ast.find_all(exp.AggFunc):
                        if aggregate.find_ancestor(exp.Select) is not ast:
                            continue
                        aggregate_codes = set()
                        for case in aggregate.find_all(exp.Case):
                            if not any(correct_column(c) for c in case.find_all(exp.Column)):
                                continue
                            literals = {
                                str(v.this) for v in case.find_all(exp.Literal) if v.is_string
                            }
                            aggregate_codes.update(
                                value.casefold() for value in matched if value in literals
                            )
                        # Each aggregate must isolate exactly one cohort.
                        if len(aggregate_codes) == 1:
                            covered.update(aggregate_codes)
                    if {v.casefold() for v in matched}.issubset(covered):
                        constrained.update(covered)
                # AND-combined positive ANY predicates require every listed
                # array value. Unlike OR or overlap, they preserve ALL-of intent.
                if not constrained and len(matched) >= 2 and where and (
                    data_type.endswith("[]") or "array" in data_type
                ):
                    required_codes = set(matched)
                    found_codes = set()
                    safe = True
                    for predicate in conjuncts(where.this):
                        columns = list(predicate.find_all(exp.Column))
                        if not any(correct_column(c) for c in columns):
                            continue
                        if not isinstance(predicate, exp.EQ):
                            safe = False
                            break
                        code = None
                        for literal, member in (
                            (predicate.this, predicate.expression),
                            (predicate.expression, predicate.this),
                        ):
                            if isinstance(literal, exp.Literal) and literal.is_string and isinstance(member, exp.Any):
                                operand = member.this.this if isinstance(member.this, exp.Paren) else member.this
                                if correct_column(operand):
                                    code = str(literal.this)
                        if code not in required_codes:
                            safe = False
                            break
                        found_codes.add(code)
                    if safe and required_codes.issubset(found_codes):
                        constrained.update(v.casefold() for v in found_codes)
                missing = [v for v in matched if v.casefold() not in constrained]
                if missing:
                    raise SQLValidationError(
                        "Generated SQL omitted explicitly compared categorical values",
                        details={"checks": [{
                            "code": "categorical_comparison_filter_violation",
                            "status": "failed", "severity": "error",
                            "message": f"Comparison on {column_name} must filter approved values: "
                                       + ", ".join(matched),
                            "column_name": column_name,
                            "canonical_values": matched,
                        }]},
                    )

    @staticmethod
    def _repair_explicit_categorical_comparison(
        sql: str, error: SQLValidationError, *, dialect: str = "postgresql",
    ) -> Optional[str]:
        """Narrowly repair an omitted governed categorical filter, never arbitrary SQL."""
        import sqlglot
        from sqlglot import exp

        checks = (getattr(error, "details", None) or {}).get("checks") or []
        if len(checks) != 1 or checks[0].get("code") != "categorical_comparison_filter_violation":
            return None
        column = checks[0].get("column_name")
        values = checks[0].get("canonical_values") or []
        if not column or not values or len({str(v).casefold() for v in values}) != len(values):
            return None
        try:
            statements = sqlglot.parse(sql, read=sqlglot_dialect(dialect))
            if len(statements) != 1 or not isinstance(statements[0], exp.Select):
                return None
            ast = statements[0]
            if any(isinstance(n, (exp.Subquery, exp.CTE, exp.Join, exp.Union, exp.SetOperation)) for n in ast.walk()):
                return None
            tables = list(ast.find_all(exp.Table))
            if len(tables) != 1:
                return None
            # Do not rewrite an existing constraint, even if incomplete: its
            # semantics may be deliberate or more complex than a simple IN.
            where = ast.args.get("where")
            if where and any(c.name.casefold() == column.casefold() for c in where.find_all(exp.Column)):
                return None
            if not any(c.name.casefold() == column.casefold() for c in ast.find_all(exp.Column)):
                return None
            qualifier = tables[0].alias_or_name
            predicate = exp.In(
                this=exp.column(column, table=qualifier),
                expressions=[exp.Literal.string(str(v)) for v in values],
            )
            ast.set("where", exp.Where(this=exp.and_(where.this.copy(), predicate) if where else predicate))
            return ast.sql(dialect=sqlglot_dialect(dialect))
        except (ValueError, TypeError, sqlglot.errors.ParseError):
            return None

    @staticmethod
    def _repair_missing_governed_filter(
        sql: str, checks: list[dict[str, Any]], *, dialect: str = "postgresql",
    ) -> Optional[str]:
        """Safely add one missing canonical equality filter to simple SQL only.

        Never modify existing predicates on the governed column or complex
        queries. All candidates must pass SQL validation and correctness again.
        """
        import sqlglot
        from sqlglot import exp
        missing = [c for c in checks if c.get("code") == "filter_violation"]
        if len(missing) != 1:
            return None
        check = missing[0]
        column = str(check.get("column") or "")
        value = check.get("expected_value")
        if check.get("data_type") in ("array", "text[]") or str(check.get("data_type") or "").endswith("[]"):
            return None
        if not column or value is None or check.get("operator") != "=":
            return None
        try:
            parsed = sqlglot.parse(sql, read=sqlglot_dialect(dialect))
            if len(parsed) != 1 or not isinstance(parsed[0], exp.Select):
                return None
            tree = parsed[0]
            if any(isinstance(node, (exp.Join, exp.Subquery, exp.CTE, exp.Union, exp.SetOperation))
                   for node in tree.walk()):
                return None
            tables = list(tree.find_all(exp.Table))
            if len(tables) != 1:
                return None
            where = tree.args.get("where")
            if where is not None and any(
                node.name.casefold() == column.casefold()
                for node in where.find_all(exp.Column)
            ):
                return None
            # An absent column in a selected table is not grounds to invent
            # a predicate. Require the column to occur elsewhere in the SQL.
            if not any(node.name.casefold() == column.casefold()
                       for node in tree.find_all(exp.Column)):
                return None
            predicate = exp.EQ(
                this=exp.column(column, table=tables[0].alias_or_name),
                expression=exp.Literal.string(str(value)),
            )
            tree.set("where", exp.Where(
                this=exp.and_(where.this.copy(), predicate) if where else predicate,
            ))
            return tree.sql(dialect=sqlglot_dialect(dialect))
        except (ValueError, TypeError, sqlglot.errors.ParseError):
            return None

    @staticmethod
    def _required_relationships(governed_context: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert governed semantic relationships into physical join invariants."""
        entities = governed_context.get("entities", [])
        entity_by_id = {entity.get("id"): entity for entity in entities}
        required: list[dict[str, Any]] = []
        for relationship in governed_context.get("relationships", []):
            left = entity_by_id.get(relationship.get("from_entity_id"))
            right = entity_by_id.get(relationship.get("to_entity_id"))
            if not left or not right:
                continue
            if not relationship.get("from_column") or not relationship.get("to_column"):
                continue
            required.append({
                "name": relationship.get("name"),
                "from_entity_id": relationship.get("from_entity_id"),
                "from_table": f"{left.get('schema_name')}.{left.get('table_name')}",
                "from_column": relationship.get("from_column"),
                "to_entity_id": relationship.get("to_entity_id"),
                "to_table": f"{right.get('schema_name')}.{right.get('table_name')}",
                "to_column": relationship.get("to_column"),
                "cardinality": relationship.get("cardinality"),
                # Only published relationship records carry this policy. Do not
                # infer a policy for legacy metadata or human review drafts.
                **({"join_policy": relationship["join_policy"],
                    "from_schema": left.get("schema_name"),
                    "to_schema": right.get("schema_name")}
                   if "join_policy" in relationship else {}),
            })
        return required

    @staticmethod
    def _required_filters(
        question: str,
        entities: list[dict[str, Any]],
        intent_filters: list[Any],
        *,
        schema: Optional[SchemaMetadata] = None,
    ) -> list[dict[str, Any]]:
        """Resolve deterministic governed filters used by generation and validation.

        The legacy entity resolver remains a valid source, but governed semantic
        attributes may also imply simple value filters (for example "red products")
        even when the attribute name is omitted.
        """
        required: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()

        def add(attribute: Any, column: Any, operator: Any, value: Any) -> None:
            column_name = str(column or "").strip()
            filter_value = str(value or "").strip()
            op = str(operator or "=").strip() or "="
            key = (column_name.casefold(), op, filter_value.casefold())
            if column_name and filter_value and key not in seen:
                seen.add(key)
                required.append({
                    "attribute": str(attribute or column_name),
                    "column_name": column_name,
                    "operator": op,
                    "value": filter_value,
                })

        for item in intent_filters:
            add(item.attribute, item.column_name, item.operator, item.value)

        # Published categorical mappings provide canonical values, not guessed
        # free-text literals. Only unique single-value columns can become
        # equality requirements; comparisons remain governed by the existing
        # multi-value SQL validator.
        published_values = []
        published_types: dict[str, str] = {}
        for entity in entities:
            for attribute in entity.get("attributes") or []:
                column = str(attribute.get("column_name") or "").strip()
                data_type = str(attribute.get("data_type") or "").casefold()
                published_types[column.casefold()] = data_type
                if data_type in {"date", "timestamp", "integer", "int", "bigint", "numeric"}:
                    continue
                for mapping in attribute.get("value_mappings") or []:
                    canonical = mapping.get("canonical_value")
                    if canonical is not None and column:
                        published_values.append({
                            "column_name": column,
                            "value": str(canonical),
                            "synonyms": mapping.get("synonyms") or [],
                        })
        resolved = resolve_categorical_intent(question, published_values)
        by_column: dict[str, set[str]] = {}
        for item in resolved:
            by_column.setdefault(item["column_name"].casefold(), set()).add(item["value"])
        for item in resolved:
            column = item["column_name"]
            # Do not force mutually exclusive equality filters or override
            # explicit filters supplied by the intent planner.
            if len(by_column[column.casefold()]) != 1:
                continue
            if any(entry["column_name"].casefold() == column.casefold() for entry in required):
                continue
            if published_types.get(column.casefold(), "").endswith("[]") or "array" in published_types.get(column.casefold(), ""):
                continue  # Array membership must be validated by its dedicated semantic guard.
            add(column, column, "=", item["value"])

        normalized_tokens = re.findall(r"[a-z0-9]+", question.casefold())
        stop_words = {
            "show", "list", "give", "find", "get", "all", "top", "bottom",
            "by", "for", "from", "with", "where", "and", "or", "the", "a", "an",
            "revenue", "sales", "amount", "units", "unit", "sold", "count",
        }
        candidate_values = [
            token for token in normalized_tokens
            if token not in stop_words and not token.isdigit()
        ]

        for entity in entities:
            entity_terms = {
                token
                for term in [entity.get("name"), *(entity.get("synonyms") or [])]
                for token in re.findall(r"[a-z0-9]+", str(term or "").casefold())
            }
            values = [token for token in candidate_values if token not in entity_terms]
            if not values:
                continue
            for attribute in entity.get("attributes") or []:
                # Published value mappings are authoritative for this attribute.
                # Do not run legacy adjective inference afterward: in a
                # comparison it can add an arbitrary equality filter even
                # when the canonical resolver correctly found two cohorts.
                if attribute.get("value_mappings"):
                    continue
                # Value-only inference is intentionally limited to categorical
                # governed attributes. Free-text/display columns must not absorb
                # arbitrary words from the question.
                data_type = str(attribute.get("data_type") or "").casefold()
                if not data_type and schema is not None:
                    table = next((table for table in schema.tables if table.name.casefold() == str(entity.get("table_name") or "").casefold() and (not entity.get("schema_name") or not table.schema_name or table.schema_name.casefold() == str(entity.get("schema_name")).casefold())), None)
                    column = table.get_column(str(attribute.get("column_name") or "")) if table is not None else None
                    data_type = str(column.data_type if column is not None else "").casefold()
                semantic_type = str(attribute.get("semantic_type") or "").casefold()
                if not (
                    semantic_type in {"category", "categorical", "dimension"}
                    or "char" in data_type
                ):
                    continue
                for value in values:
                    # A bare adjective/noun immediately before the governed entity
                    # is a conservative value-only filter form: "red products".
                    pattern_terms = [entity.get("name"), *(entity.get("synonyms") or [])]
                    if any(
                        re.search(
                            rf"\b{re.escape(value)}\s+{re.escape(str(term or '').casefold())}s?\b",
                            question.casefold(),
                        )
                        for term in pattern_terms if str(term or "").strip()
                    ):
                        add(attribute.get("name"), attribute.get("column_name"), "=", value)
                        break

        return required

    @staticmethod
    def _required_grouping_columns(
        question: str,
        entities: list[dict[str, Any]],
        *,
        selected_attribute: Optional[dict[str, Any]] = None,
        metrics: Optional[list[dict[str, Any]]] = None,
        schema: Optional[SchemaMetadata] = None,
    ) -> list[str]:
        """Resolve explicit grouping to the most specific governed dimension."""
        normalized = " ".join(re.findall(r"[a-z0-9]+", question.casefold()))

        # Rank the subject, not the metric or a filter-only attribute. When
        # the published entity omits an attribute, resolve an exact humanized
        # column name from the inspected physical schema; never invent one.
        ranked_subject = None
        ranked = re.search(r"\\btop\\s+\\d+\\s+(.+?)\\s+by\\b", normalized)
        if ranked:
            ranked_subject = ranked.group(1)
        elif re.search(r"\\btop\\s+\\d+\\s+by\\b", normalized):
            subject = re.search(
                r"\\bwhich\\s+(.+?)\\s+(?:have|has|are|were|manage|manages)\\b",
                normalized,
            )
            if subject:
                ranked_subject = subject.group(1)
        if ranked_subject and schema is not None:
            # Compare tokenized schema column names to the ranked subject,
            # allowing a trailing plural on words without changing column IDs.
            # A column is eligible only when the subject actually names it.
            def singular_tokens(value: str) -> list[str]:
                return [
                    token[:-3] + "y" if token.endswith("ies") and len(token) > 4
                    else token[:-1] if token.endswith("s") and not token.endswith("ss") and len(token) > 3
                    else token
                    for token in re.findall(r"[a-z0-9]+", value.casefold())
                ]

            subject_tokens = singular_tokens(ranked_subject)
            matches = []
            for table in getattr(schema, "tables", []) or []:
                for column in getattr(table, "columns", []) or []:
                    name = str(getattr(column, "name", "") or "")
                    column_tokens = singular_tokens(name)
                    if not column_tokens:
                        continue
                    if any(subject_tokens[i:i + len(column_tokens)] == column_tokens
                           for i in range(len(subject_tokens) - len(column_tokens) + 1)):
                        matches.append((len(column_tokens), name))
            if matches:
                longest = max(length for length, _ in matches)
                selected = {name for length, name in matches if length == longest}
                if len(selected) == 1:
                    return list(selected)

        # Resolve an elliptical ranking such as "Which suppliers have late
        # orders? Show the top 10 by order count" from its preceding subject.
        elliptical = re.search(r"\btop\s+\d+\s+by\b", normalized)
        if elliptical:
            preceding = normalized[:elliptical.start()]
            # In "Which customers have overdue invoices?", invoices are
            # objects of the predicate, not the ranked subject.
            subject = re.search(r"\bwhich\s+(.+?)\s+(?:have|has|are|were|manage|manages)\b", preceding)
            if subject:
                preceding = subject.group(1)
            candidates = []
            for entity in entities:
                dimensions = [
                    (entity.get("display_column") or entity.get("key_column"),
                     [entity.get("name"), *(entity.get("synonyms") or [])])
                ] + [
                    (attribute.get("column_name"),
                     [attribute.get("name"), *(attribute.get("synonyms") or [])])
                    for attribute in entity.get("attributes") or []
                ]
                for column, terms in dimensions:
                    for term in terms:
                        phrase = " ".join(re.findall(r"[a-z0-9]+", str(term or "").casefold()))
                        if column and phrase and re.search(rf"\b{re.escape(phrase)}(?:s)?\b", preceding):
                            candidates.append((len(phrase.split()), str(column)))
            if candidates:
                best = max(score for score, _ in candidates)
                columns = {column for score, column in candidates if score == best}
                if len(columns) == 1:
                    return list(columns)

        # A selected attribute can be a filter-only dimension. Do not let
        # its presence override the grain of an explicit top-N ranking.
        is_top_ranking = bool(re.search(r"\btop\s+\d+\b", normalized))
        if selected_attribute and not is_top_ranking:
            selected_column = str(
                selected_attribute.get("column_name")
                or selected_attribute.get("column")
                or ""
            ).strip()
            if selected_column:
                return [selected_column]

        # In ranking forms such as "top customers by order count", "by" names
        # the ranking metric rather than a grouping dimension. Group by the
        # requested entity instead.
        metric_terms = []
        for metric in metrics or []:
            metric_terms.extend([metric.get("name"), *(metric.get("synonyms") or [])])
        ranking_metric_matches: list[re.Match[str]] = []
        for term in metric_terms:
            semantic = " ".join(
                re.findall(r"[a-z0-9]+", str(term or "").casefold())
            )
            if not semantic:
                continue
            ranking_metric_matches.extend(
                re.finditer(
                    rf"\bby\s+{re.escape(semantic)}\b",
                    normalized,
                )
            )

        if ranking_metric_matches:
            # Resolve the entity from the text before the actual governed
            # "by <metric>" ranking clause. Prefer the right-most match so
            # earlier language cannot accidentally define the grouping grain.
            ranking_match = max(
                ranking_metric_matches,
                key=lambda match: match.start(),
            )
            prefix = normalized[:ranking_match.start()].strip()

            # Metric names can contain entity terms (for example "order count"
            # contains the Sales Order synonym "order"). Remove complete
            # governed metric phrases before resolving the ranked entity so
            # metric vocabulary cannot leak into dimensional grouping.
            entity_prefix = prefix
            normalized_metric_terms = sorted(
                {
                    " ".join(
                        re.findall(r"[a-z0-9]+", str(term or "").casefold())
                    )
                    for term in metric_terms
                    if str(term or "").strip()
                },
                key=lambda value: len(value.split()),
                reverse=True,
            )
            for metric_semantic in normalized_metric_terms:
                if metric_semantic:
                    entity_prefix = re.sub(
                        rf"\b{re.escape(metric_semantic)}\b",
                        " ",
                        entity_prefix,
                    )
            entity_prefix = " ".join(entity_prefix.split())

            entity_candidates: list[tuple[int, str]] = []
            for entity in entities:
                column = str(
                    entity.get("display_column") or entity.get("key_column") or ""
                ).strip()
                if not column:
                    continue
                for term in [entity.get("name"), *(entity.get("synonyms") or [])]:
                    semantic = " ".join(
                        re.findall(r"[a-z0-9]+", str(term or "").casefold())
                    )
                    if semantic and re.search(
                        rf"\b{re.escape(semantic)}(?:s)?\b",
                        entity_prefix,
                    ):
                        entity_candidates.append((len(semantic.split()), column))
            if entity_candidates:
                best = max(score for score, _ in entity_candidates)
                return list(dict.fromkeys(
                    column for score, column in entity_candidates if score == best
                ))

        # A ranked entity defines the grain even when the metric is not
        # published under the exact wording used in the question. Restrict
        # matching to the entity phrase before "by" so subsequent filter
        # clauses cannot accidentally become grouping dimensions.
        ranking = re.search(r"\btop\s+\d+\s+(.+?)\s+by\b", normalized)
        if ranking:
            # A governed dimension immediately after "by" takes precedence
            # over the ranked entity. For example, "top products by colour"
            # requests colour grouping, not a product ranking by a metric.
            by_phrase = normalized[ranking.end():].strip()
            dimension_matches = []
            for entity in entities:
                for attribute in entity.get("attributes") or []:
                    column = str(attribute.get("column_name") or "").strip()
                    if not column:
                        continue
                    terms = [attribute.get("name"), *(attribute.get("synonyms") or [])]
                    entity_terms = [entity.get("name"), *(entity.get("synonyms") or [])]
                    for term in terms:
                        phrase = " ".join(re.findall(r"[a-z0-9]+", str(term or "").casefold()))
                        if not phrase:
                            continue
                        candidates = [phrase]
                        for entity_term in entity_terms:
                            prefix = " ".join(re.findall(r"[a-z0-9]+", str(entity_term or "").casefold()))
                            if prefix:
                                candidates.append(prefix + " " + phrase)
                        if any(by_phrase == candidate or by_phrase.startswith(candidate + " ")
                               for candidate in candidates):
                            dimension_matches.append((max(len(x.split()) for x in candidates), column))
            if dimension_matches:
                best = max(score for score, _ in dimension_matches)
                return list(dict.fromkeys(column for score, column in dimension_matches if score == best))
            ranked_phrase = ranking.group(1)
            candidates = []
            for entity in entities:
                column = str(entity.get("display_column") or entity.get("key_column") or "").strip()
                if not column:
                    continue
                for term in [entity.get("name"), *(entity.get("synonyms") or [])]:
                    phrase = " ".join(re.findall(r"[a-z0-9]+", str(term or "").casefold()))
                    if phrase and re.search(rf"\b{re.escape(phrase)}(?:s)?\b", ranked_phrase):
                        candidates.append((len(phrase.split()), column))
            # Ranked dimensions may be governed attributes rather than entities.
            # Resolve them only in the phrase before the metric's "by" clause.
            for entity in entities:
                for attribute in entity.get("attributes") or []:
                    column = str(attribute.get("column_name") or "").strip()
                    if not column:
                        continue
                    for term in [attribute.get("name"), *(attribute.get("synonyms") or [])]:
                        phrase = " ".join(re.findall(r"[a-z0-9]+", str(term or "").casefold()))
                        if phrase and re.search(rf"\b{re.escape(phrase)}(?:s)?\b", ranked_phrase):
                            candidates.append((len(phrase.split()), column))
            if candidates:
                best = max(score for score, _ in candidates)
                return list(dict.fromkeys(column for score, column in candidates if score == best))
            # No verified ranked dimension: fail closed instead of treating
            # attributes mentioned later in WHERE-like clauses as GROUP BY.
            return []

        attribute_matches: list[tuple[int, str]] = []
        entity_matches: list[tuple[int, str]] = []

        # For ordinary aggregation questions, every governed dimension explicitly
        # named in the grouping clause contributes to the required grain. Earlier
        # logic required each dimension to be immediately preceded by "by", which
        # dropped later dimensions in forms such as
        # "by customer country and customer segment".
        grouping_clause = ""
        grouping_match = re.search(r"\bby\s+(.+)$", normalized)
        if grouping_match:
            grouping_clause = grouping_match.group(1).strip()

        for entity in entities:
            for attribute in entity.get("attributes") or []:
                column = str(attribute.get("column_name") or "").strip()
                if not column:
                    continue
                for term in [attribute.get("name"), *(attribute.get("synonyms") or [])]:
                    semantic = " ".join(
                        re.findall(r"[a-z0-9]+", str(term or "").casefold())
                    )
                    if not semantic:
                        continue
                    if re.search(
                        rf"\bby\s+(?:each\s+)?{re.escape(semantic)}(?:s)?\b",
                        normalized,
                    ):
                        attribute_matches.append((len(semantic.split()), column))
                        continue

                    if grouping_clause and re.search(
                        rf"\b{re.escape(semantic)}(?:s)?\b",
                        grouping_clause,
                    ):
                        attribute_matches.append((len(semantic.split()), column))
                        continue

                    # Governed entity + attribute composition: semantic catalogs
                    # often store "Product" and "Color"/"colour" separately while
                    # users naturally ask for "by product colour".
                    for entity_term in [
                        entity.get("name"),
                        *(entity.get("synonyms") or []),
                    ]:
                        entity_semantic = " ".join(
                            re.findall(
                                r"[a-z0-9]+",
                                str(entity_term or "").casefold(),
                            )
                        )
                        composed_pattern = (
                            rf"\b{re.escape(entity_semantic)}(?:s)?\s+"
                            rf"{re.escape(semantic)}(?:s)?\b"
                        )
                        if entity_semantic and (
                            re.search(
                                rf"\bby\s+(?:each\s+)?"
                                + composed_pattern.removeprefix(r"\b"),
                                normalized,
                            )
                            or (
                                grouping_clause
                                and re.search(composed_pattern, grouping_clause)
                            )
                        ):
                            attribute_matches.append(
                                (len(entity_semantic.split()) + len(semantic.split()), column)
                            )
                            break

            entity_column = str(
                entity.get("display_column") or entity.get("key_column") or ""
            ).strip()
            if entity_column:
                for term in [entity.get("name"), *(entity.get("synonyms") or [])]:
                    semantic = " ".join(
                        re.findall(r"[a-z0-9]+", str(term or "").casefold())
                    )
                    if semantic and re.search(
                        rf"\bby\s+(?:each\s+)?{re.escape(semantic)}(?:s)?\b",
                        normalized,
                    ):
                        entity_matches.append((len(semantic.split()), entity_column))

        matches = attribute_matches or entity_matches
        if not matches:
            return []

        # Attribute matches are authoritative governed dimensions. Preserve every
        # distinct explicitly requested attribute in a multi-dimension grouping
        # clause instead of discarding shorter phrases merely because another
        # dimension has a more specific composed name.
        if attribute_matches:
            result: list[str] = []
            seen: set[str] = set()
            for _, column in attribute_matches:
                key = column.casefold()
                if key not in seen:
                    seen.add(key)
                    result.append(column)
            return result

        max_specificity = max(score for score, _ in entity_matches)
        result = []
        seen: set[str] = set()
        for score, column in entity_matches:
            key = column.casefold()
            if score == max_specificity and key not in seen:
                seen.add(key)
                result.append(column)
        return result

    @staticmethod
    def _merge_resolved_parameters(
        parameters: Dict[str, Any],
        intent: QueryIntent,
    ) -> Dict[str, Any]:
        """Fill missing parameters from deterministic semantic filters."""
        merged = dict(parameters)
        for item in intent.filters:
            for key in (item.attribute, item.column_name):
                if key not in merged:
                    merged[key] = item.value
        return merged

