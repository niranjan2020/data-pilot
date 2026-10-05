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
from datapilot.application.services.query_correctness import assess_query_correctness
from datapilot.core.exceptions import SemanticRetrievalError, SQLValidationError, TimeInterpretationError
from datapilot.core.logging import get_logger
from datapilot.domain.interfaces.database import DatabaseProvider
from datapilot.domain.interfaces.entity_resolver import EntityResolver
from datapilot.domain.interfaces.query_policy import QueryPolicyEnforcer
from datapilot.domain.interfaces.semantic import SemanticCatalogProvider
from datapilot.domain.interfaces.semantic_retriever import SemanticRetriever
from datapilot.domain.interfaces.sql_generator import SQLGenerator
from datapilot.domain.interfaces.sql_validator import SQLValidator
from datapilot.domain.models import SchemaMetadata
from datapilot.domain.policies import QueryExecutionPolicy
from datapilot.domain.query import ClarificationOption, ClarificationRequest, QueryRequest, QueryResponse, QueryTrace
from datapilot.domain.semantic import QueryIntent, SemanticCatalog
from datapilot.infrastructure.sql.query_policy import SQLQueryPolicyEnforcer
from datapilot.infrastructure.sql.identifier_binding import bind_physical_identifiers


logger = get_logger("datapilot.query")

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
        context_budget_chars: int = 24000,
    ) -> None:
        self._database = database_provider
        self._validator = sql_validator
        self._sql_generator = sql_generator
        self._semantic_catalog_provider = semantic_catalog_provider
        self._semantic_retriever = semantic_retriever
        self._semantic_retrieval_limit = semantic_retrieval_limit
        self._semantic_context_assembler = semantic_context_assembler
        self._context_budgeter = ContextBudgeter(context_budget_chars)
        self._entity_resolver = entity_resolver or DeterministicEntityResolver()
        self._query_policy = query_policy or QueryExecutionPolicy()
        if query_timeout_seconds is not None:
            self._query_policy = self._query_policy.model_copy(
                update={"timeout_seconds": query_timeout_seconds}
            )
        self._query_policy_enforcer = query_policy_enforcer or SQLQueryPolicyEnforcer()

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
        )
        catalog = catalog or await self._semantic_catalog_provider.get_catalog()

        resolver_catalog = catalog
        selected_entity = effective_clarifications.get("entity")
        if selected_entity:
            selected_entities = [
                entity for entity in catalog.entities
                if entity.name.casefold() == selected_entity.casefold()
            ]
            if not selected_entities:
                return QueryResponse(
                    question=request.question,
                    status="rejected",
                    trace=trace,
                    message=(
                        f"The selected entity {selected_entity!r} is not present in the "
                        "governed semantic catalog. No SQL was generated."
                    ),
                )
            resolver_catalog = catalog.model_copy(update={"entities": selected_entities})

        intent = self._entity_resolver.resolve(contextual_question, resolver_catalog, schema)
        if (
            catalog.entities
            and intent.entity is None
            and not intent.ambiguities
        ):
            return QueryResponse(
                question=request.question,
                status="rejected",
                confidence=intent.confidence,
                resolved_intent=intent,
                trace=trace,
                message=(
                    "I could not map this question to a governed business entity. "
                    "No SQL was generated."
                ),
            )
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
            return QueryResponse(
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
            )

        selected_metric = effective_clarifications.get("metric")
        governed_metrics = governed_context.get("metrics", [])
        if selected_metric:
            selected_metrics = [
                metric for metric in governed_metrics
                if str(metric.get("name") or "").casefold() == selected_metric.casefold()
            ]
            if not selected_metrics:
                return QueryResponse(
                    question=request.question,
                    status="rejected",
                    confidence=intent.confidence,
                    resolved_intent=intent,
                    trace=trace,
                    message=(
                        f"The selected metric {selected_metric!r} is not present in the "
                        "governed semantic context. No SQL was generated."
                    ),
                )
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
                return QueryResponse(
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
                )

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
                return QueryResponse(
                    question=request.question,
                    status="rejected",
                    confidence=intent.confidence,
                    resolved_intent=intent,
                    trace=trace,
                    message=(
                        f"The selected attribute {selected_attribute!r} is not present in the "
                        "governed semantic context. No SQL was generated."
                    ),
                )
            governed_context["resolved_attribute_selection"] = selected
        elif len(attribute_candidates) > 1:
            return QueryResponse(
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
            )

        governed_filters = self._required_filters(
            contextual_question,
            governed_context.get("entities", []),
            intent.filters,
        )
        governed_grouping_columns = self._required_grouping_columns(
            contextual_question,
            governed_context.get("entities", []),
            selected_attribute=governed_context.get("resolved_attribute_selection"),
            metrics=governed_context.get("metrics", []),
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
                return QueryResponse(
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
                )
            governed_context["resolved_time_filter"] = time_interpretation
        generation_context = {
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
        bound_sql = bind_physical_identifiers(generated, schema, self._database.dialect)
        trace.bound_sql = bound_sql
        logger.info("query catalog_bound_sql=%s", bound_sql)
        return await self._validate_and_execute(
            question=request.question,
            sql=bound_sql,
            source="generator",
            confidence=intent.confidence,
            resolved_intent=intent,
            retrieved_context=retrieved_context,
            trace=trace,
            execute=not request.dry_run,
            governed_tables=trace.physical_tables,
            governed_metrics=governed_context.get("metrics", []),
            required_grouping_columns=governed_grouping_columns,
            required_filters=governed_filters,
            required_relationships=self._required_relationships(governed_context),
            required_time_plan=time_interpretation,
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
        required_relationships: Optional[list[dict[str, Any]]] = None,
        required_time_plan: Optional[dict[str, Any]] = None,
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

        executable_sql = validation.sanitized_sql or sql
        if trace is not None:
            trace.validated_sql = executable_sql
            trace.validation_affected_tables = list(validation.affected_tables)
            trace.validation_warnings = list(validation.warnings)
        logger.info(
            "query validated_sql=%s affected_tables=%s warnings=%s",
            executable_sql, validation.affected_tables, validation.warnings,
        )

        correctness_checks = assess_query_correctness(
            affected_tables=validation.affected_tables,
            governed_tables=governed_tables or [],
            sql=executable_sql,
            governed_metrics=governed_metrics or [],
            required_grouping_columns=required_grouping_columns or [],
            required_filters=required_filters or [],
            required_relationships=required_relationships or [],
            required_time_plan=required_time_plan,
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
            return QueryResponse(
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
            )

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

        return QueryResponse(
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
        )

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

        # An explicit semantic attribute reference is stronger than generic
        # "in/within" phrasing and must not be mixed with fallback candidates.
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
            })
        return required

    @staticmethod
    def _required_filters(
        question: str,
        entities: list[dict[str, Any]],
        intent_filters: list[Any],
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
                # Value-only inference is intentionally limited to categorical
                # governed attributes. Free-text/display columns must not absorb
                # arbitrary words from the question.
                data_type = str(attribute.get("data_type") or "").casefold()
                semantic_type = str(attribute.get("semantic_type") or "").casefold()
                name = str(attribute.get("name") or "")
                if not (
                    semantic_type in {"category", "categorical", "dimension"}
                    or name.casefold() in {"color", "colour"}
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
    ) -> list[str]:
        """Resolve explicit grouping to the most specific governed dimension."""
        if selected_attribute:
            selected_column = str(
                selected_attribute.get("column_name")
                or selected_attribute.get("column")
                or ""
            ).strip()
            if selected_column:
                return [selected_column]

        normalized = " ".join(re.findall(r"[a-z0-9]+", question.casefold()))

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

