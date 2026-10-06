"""Tests for the provider-independent NL-to-SQL orchestration boundary."""

from __future__ import annotations

import pytest

from datapilot.core.exceptions import DatabaseExecutionError, SemanticRetrievalError, SQLValidationError, TimeInterpretationError
from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.domain.models import SchemaMetadata
from datapilot.domain.policies import QueryExecutionPolicy
from datapilot.domain.query import QueryRequest
from datapilot.domain.semantic import EntityDefinition, SemanticCatalog


class FakeDatabase:
    dialect = "postgresql"

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.timeouts: list[float | None] = []

    async def introspect_schema(self, schema_name=None):
        return SchemaMetadata(schema_name=schema_name, dialect=self.dialect)

    async def execute_query(self, sql: str, params=None, timeout_seconds=None):
        from datapilot.domain.models import QueryResult
        self.executed.append(sql)
        self.timeouts.append(timeout_seconds)
        return QueryResult(columns=["count"], rows=[[3]], row_count=1)


class FakeValidator:
    async def validate(self, sql, dialect=None, enforce_read_only=True):
        from datapilot.domain.models import SQLValidationResult
        return SQLValidationResult(
            is_valid=True,
            is_read_only=True,
            sanitized_sql=sql,
            warnings=["Query has no LIMIT clause"],
        )


class FakeSQLGenerator:
    def __init__(self, sql: str = "SELECT COUNT(*) AS count FROM records") -> None:
        self.sql = sql
        self.calls = 0
        self.contexts = []

    async def generate(self, question, schema, context=None, dialect=None):
        self.calls += 1
        assert dialect == "postgresql"
        assert context is not None
        assert "semantic_catalog" in context
        assert "query_intent" in context
        self.contexts.append(context)
        governed_context = context.get("governed_semantic_context") or {}
        grouping = governed_context.get("required_grouping_columns") or []
        if grouping and self.sql == "SELECT COUNT(*) AS count FROM records":
            columns = ", ".join(grouping)
            return f"SELECT {columns}, COUNT(*) AS count FROM records GROUP BY {columns}"
        return self.sql


class FakeCatalog:
    def __init__(self, catalog: SemanticCatalog) -> None:
        self.catalog = catalog

    async def get_catalog(self) -> SemanticCatalog:
        return self.catalog


@pytest.mark.asyncio
async def test_aggregate_generator_query_does_not_receive_arbitrary_limit():
    database = FakeDatabase()
    generator = FakeSQLGenerator("SELECT COUNT(*) AS count FROM records")
    orchestrator = QueryOrchestrator(
        database, FakeValidator(), generator, FakeCatalog(SemanticCatalog())
    )

    response = await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert response.source == "generator"
    assert response.sql == "SELECT COUNT(*) AS count FROM records"
    assert generator.calls == 1


@pytest.mark.asyncio
async def test_non_aggregate_generator_query_receives_policy_limit():
    database = FakeDatabase()
    generator = FakeSQLGenerator("SELECT id, name FROM records")
    orchestrator = QueryOrchestrator(
        database,
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
        query_policy=QueryExecutionPolicy(default_limit=25),
    )

    response = await orchestrator.query(QueryRequest(question="show records"))

    assert response.source == "generator"
    assert response.sql.endswith("LIMIT 25")
    assert database.executed == [response.sql]




def test_follow_up_contextualization_carries_semantics_without_sql():
    text = QueryOrchestrator._contextualize_follow_up(
        "Only red products",
        {
            "previous_question": "Show top 10 products by revenue",
            "governed_metrics": ["Revenue"],
            "governed_entities": ["Product", "Sales Order Line"],
            "previous_sql": "SELECT secret_should_not_be_reused",
        },
    )

    assert "Show top 10 products by revenue" in text
    assert "Only red products" in text
    assert "Revenue" in text
    assert "Product" in text
    assert "SELECT secret_should_not_be_reused" not in text


@pytest.mark.asyncio
async def test_follow_up_context_is_visible_to_generator_and_trace():
    generator = FakeSQLGenerator("SELECT COUNT(*) AS count FROM records")
    orchestrator = QueryOrchestrator(
        FakeDatabase(), FakeValidator(), generator, FakeCatalog(SemanticCatalog())
    )
    context = {
        "parent_history_id": 42,
        "previous_question": "Show revenue by product",
        "governed_metrics": ["Revenue"],
        "governed_entities": ["Product"],
    }

    response = await orchestrator.query(
        QueryRequest(question="Only red products"),
        conversation_context=context,
    )

    assert generator.contexts[0]["conversation_context"] == context
    assert response.trace is not None
    assert response.trace.conversation_context == context


def test_chained_follow_up_contextualization_uses_full_analytical_lineage():
    text = QueryOrchestrator._contextualize_follow_up(
        "Top 5 only",
        {
            "previous_question": "Only red products",
            "analytical_turns": [
                "Show top 10 products by revenue",
                "Only red products",
            ],
            "governed_metrics": ["Revenue"],
            "governed_entities": ["Product", "Sales Order Line"],
        },
    )

    assert "Show top 10 products by revenue" in text
    assert "Only red products" in text
    assert "Top 5 only" in text
    assert text.index("Show top 10 products by revenue") < text.index("Only red products")
    assert text.index("Only red products") < text.index("Top 5 only")


@pytest.mark.asyncio
async def test_entity_ambiguity_returns_structured_clarification_before_sql_generation():
    generator = FakeSQLGenerator()
    catalog = SemanticCatalog(entities=[
        EntityDefinition(name="Customer Account", description="A customer account", synonyms=["account"], table_name="customers", key_column="id"),
        EntityDefinition(name="Supplier Account", description="A supplier account", synonyms=["account"], table_name="suppliers", key_column="id"),
    ])
    orchestrator = QueryOrchestrator(
        FakeDatabase(), FakeValidator(), generator, FakeCatalog(catalog)
    )

    response = await orchestrator.query(QueryRequest(question="Show account"))

    assert response.status == "ambiguous"
    assert response.clarification is not None
    assert response.clarification.kind == "entity"
    assert response.clarification.key == "entity"
    assert {option.value for option in response.clarification.options} == {
        "Customer Account", "Supplier Account"
    }
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_entity_clarification_selection_resumes_query_generation():
    generator = FakeSQLGenerator()
    catalog = SemanticCatalog(entities=[
        EntityDefinition(name="Customer Account", description="A customer account", synonyms=["account"], table_name="customers", key_column="id"),
        EntityDefinition(name="Supplier Account", description="A supplier account", synonyms=["account"], table_name="suppliers", key_column="id"),
    ])
    orchestrator = QueryOrchestrator(
        FakeDatabase(), FakeValidator(), generator, FakeCatalog(catalog)
    )

    response = await orchestrator.query(QueryRequest(
        question="Show account",
        clarification_selections={"entity": "Customer Account"},
    ))

    assert response.status == "completed"
    assert response.resolved_intent is not None
    assert response.resolved_intent.entity is not None
    assert response.resolved_intent.entity.name == "Customer Account"
    assert generator.calls == 1
    assert generator.contexts[0]["clarification_selections"] == {"entity": "Customer Account"}


class FakeSemanticContextAssembler:
    async def assemble(self, source_name, retrieved_context, question):
        return {
            "datasets": [],
            "entities": [],
            "relationships": [],
            "metrics": [
                {"name": "Revenue", "description": "Total sales revenue", "synonyms": ["sales"]},
                {"name": "Units Sold", "description": "Total units sold", "synonyms": ["sales"]},
            ],
            "business_rules": [],
            "time_dimensions": [],
        }

    async def carry_forward(self, source_name, governed_context, conversation_context):
        return governed_context


class FakeSemanticRetriever:
    async def search(self, source_name, question, limit):
        return []


@pytest.mark.asyncio
async def test_metric_ambiguity_returns_structured_clarification_before_sql_generation():
    generator = FakeSQLGenerator()
    orchestrator = QueryOrchestrator(
        FakeDatabase(),
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
        semantic_retriever=FakeSemanticRetriever(),
        semantic_context_assembler=FakeSemanticContextAssembler(),
    )

    response = await orchestrator.query(
        QueryRequest(question="Show sales", source_name="AdventureWorks")
    )

    assert response.status == "ambiguous"
    assert response.clarification is not None
    assert response.clarification.kind == "metric"
    assert response.clarification.key == "metric"
    assert {option.value for option in response.clarification.options} == {
        "Revenue", "Units Sold"
    }
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_metric_clarification_selection_resumes_with_only_selected_metric():
    generator = FakeSQLGenerator()
    orchestrator = QueryOrchestrator(
        FakeDatabase(),
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
        semantic_retriever=FakeSemanticRetriever(),
        semantic_context_assembler=FakeSemanticContextAssembler(),
    )

    response = await orchestrator.query(QueryRequest(
        question="Show sales",
        source_name="AdventureWorks",
        clarification_selections={"metric": "Revenue"},
    ))

    assert response.status == "completed"
    assert generator.calls == 1
    metrics = generator.contexts[0]["governed_semantic_context"]["metrics"]
    assert [metric["name"] for metric in metrics] == ["Revenue"]
    assert generator.contexts[0]["clarification_selections"] == {"metric": "Revenue"}



class FakeDistinctMetricSemanticContextAssembler:
    async def assemble(self, source_name, retrieved_context, question):
        return {
            "datasets": [],
            "entities": [],
            "relationships": [],
            "metrics": [
                {"name": "Revenue", "description": "Total sales revenue", "synonyms": ["sales amount"]},
                {"name": "Units Sold", "description": "Total units sold", "synonyms": ["quantity sold"]},
                {"name": "Order Count", "description": "Distinct orders", "synonyms": ["orders"]},
            ],
            "business_rules": [],
            "time_dimensions": [],
        }

    async def carry_forward(self, source_name, governed_context, conversation_context):
        return governed_context


@pytest.mark.asyncio
async def test_distinct_explicit_metrics_are_composed_without_clarification():
    generator = FakeSQLGenerator()
    orchestrator = QueryOrchestrator(
        FakeDatabase(),
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
        semantic_retriever=FakeSemanticRetriever(),
        semantic_context_assembler=FakeDistinctMetricSemanticContextAssembler(),
    )

    response = await orchestrator.query(
        QueryRequest(
            question="Show revenue and units sold by product",
            source_name="AdventureWorks",
        )
    )

    assert response.status == "completed"
    assert response.clarification is None
    assert generator.calls == 1
    metrics = generator.contexts[0]["governed_semantic_context"]["metrics"]
    assert [metric["name"] for metric in metrics] == ["Revenue", "Units Sold"]
    assert response.trace is not None
    assert response.trace.governed_metrics == ["Revenue", "Units Sold"]


class FakeAttributeSemanticContextAssembler:
    async def assemble(self, source_name, retrieved_context, question):
        return {
            "datasets": [],
            "entities": [
                {
                    "id": 101,
                    "name": "Customer",
                    "schema_name": "Sales",
                    "table_name": "Customer",
                    "attributes": [
                        {"name": "Billing Region", "column_name": "BillingRegion", "synonyms": ["region"], "description": "Customer billing region"},
                        {"name": "Shipping Region", "column_name": "ShippingRegion", "synonyms": ["region"], "description": "Customer shipping region"},
                    ],
                }
            ],
            "relationships": [],
            "metrics": [],
            "business_rules": [],
            "time_dimensions": [],
        }

    async def carry_forward(self, source_name, governed_context, conversation_context):
        return governed_context


@pytest.mark.asyncio
async def test_attribute_ambiguity_returns_structured_clarification_before_sql_generation():
    generator = FakeSQLGenerator()
    orchestrator = QueryOrchestrator(
        FakeDatabase(),
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
        semantic_retriever=FakeSemanticRetriever(),
        semantic_context_assembler=FakeAttributeSemanticContextAssembler(),
    )

    response = await orchestrator.query(
        QueryRequest(question="Show customers by region", source_name="AdventureWorks")
    )

    assert response.status == "ambiguous"
    assert response.clarification is not None
    assert response.clarification.kind == "attribute"
    assert response.clarification.key == "attribute"
    assert {option.value for option in response.clarification.options} == {
        "Customer.Billing Region", "Customer.Shipping Region"
    }
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_attribute_clarification_selection_resumes_with_selected_attribute_hint():
    generator = FakeSQLGenerator()
    orchestrator = QueryOrchestrator(
        FakeDatabase(),
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
        semantic_retriever=FakeSemanticRetriever(),
        semantic_context_assembler=FakeAttributeSemanticContextAssembler(),
    )

    response = await orchestrator.query(QueryRequest(
        question="Show customers by region",
        source_name="AdventureWorks",
        clarification_selections={"attribute": "Customer.Shipping Region"},
    ))

    assert response.status == "completed"
    assert generator.calls == 1
    selection = generator.contexts[0]["governed_semantic_context"]["resolved_attribute_selection"]
    assert selection["entity"] == "Customer"
    assert selection["attribute"] == "Shipping Region"
    assert selection["column_name"] == "ShippingRegion"


class FakeLocationFilterSemanticContextAssembler:
    async def assemble(self, source_name, retrieved_context, question):
        return {
            "datasets": [],
            "entities": [
                {
                    "id": 102,
                    "name": "Customer",
                    "schema_name": "Sales",
                    "table_name": "Customer",
                    "attributes": [
                        {"name": "City", "column_name": "City", "synonyms": []},
                        {"name": "Country", "column_name": "Country", "synonyms": []},
                    ],
                }
            ],
            "relationships": [],
            "metrics": [],
            "business_rules": [],
            "time_dimensions": [],
        }

    async def carry_forward(self, source_name, governed_context, conversation_context):
        return governed_context


@pytest.mark.asyncio
async def test_value_only_location_filter_ambiguity_uses_only_governed_attributes():
    generator = FakeSQLGenerator()
    orchestrator = QueryOrchestrator(
        FakeDatabase(),
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
        semantic_retriever=FakeSemanticRetriever(),
        semantic_context_assembler=FakeLocationFilterSemanticContextAssembler(),
    )

    response = await orchestrator.query(
        QueryRequest(question="Show customers in London", source_name="AdventureWorks")
    )

    assert response.status == "ambiguous"
    assert response.clarification is not None
    assert response.clarification.kind == "attribute"
    assert {option.value for option in response.clarification.options} == {
        "Customer.City", "Customer.Country"
    }
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_follow_up_inherits_prior_attribute_clarification_without_reasking():
    generator = FakeSQLGenerator()
    orchestrator = QueryOrchestrator(
        FakeDatabase(),
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
        semantic_retriever=FakeSemanticRetriever(),
        semantic_context_assembler=FakeAttributeSemanticContextAssembler(),
    )
    context = {
        "previous_question": "Show customers by region",
        "analytical_turns": ["Show customers by region"],
        "clarification_selections": {"attribute": "Customer.Shipping Region"},
    }

    response = await orchestrator.query(
        QueryRequest(question="Only active customers", source_name="AdventureWorks"),
        conversation_context=context,
    )

    assert response.status == "completed"
    assert response.clarification is None
    assert generator.calls == 1
    assert generator.contexts[0]["clarification_selections"] == {
        "attribute": "Customer.Shipping Region"
    }
    selection = generator.contexts[0]["governed_semantic_context"]["resolved_attribute_selection"]
    assert selection["attribute"] == "Shipping Region"
    assert response.trace is not None
    assert response.trace.clarification_selections == {
        "attribute": "Customer.Shipping Region"
    }


@pytest.mark.asyncio
async def test_current_clarification_overrides_inherited_follow_up_selection():
    generator = FakeSQLGenerator()
    orchestrator = QueryOrchestrator(
        FakeDatabase(),
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
        semantic_retriever=FakeSemanticRetriever(),
        semantic_context_assembler=FakeAttributeSemanticContextAssembler(),
    )
    context = {
        "previous_question": "Show customers by region",
        "clarification_selections": {"attribute": "Customer.Shipping Region"},
    }

    response = await orchestrator.query(
        QueryRequest(
            question="Show customers by region",
            source_name="AdventureWorks",
            clarification_selections={"attribute": "Customer.Billing Region"},
        ),
        conversation_context=context,
    )

    assert response.status == "completed"
    selection = generator.contexts[0]["governed_semantic_context"]["resolved_attribute_selection"]
    assert selection["attribute"] == "Billing Region"
    assert response.trace is not None
    assert response.trace.clarification_selections["attribute"] == "Customer.Billing Region"


def test_required_grouping_columns_resolves_entity_and_attribute_synonym():
    entities = [{
        "name": "Product",
        "synonyms": ["item"],
        "display_column": "Name",
        "key_column": "ProductID",
        "attributes": [{
            "name": "Color",
            "column_name": "Color",
            "synonyms": ["product colour"],
        }],
    }]

    assert QueryOrchestrator._required_grouping_columns(
        "Show revenue by product", entities
    ) == ["Name"]
    assert QueryOrchestrator._required_grouping_columns(
        "Show top 10 products by product colour", entities
    ) == ["Color"]


def test_required_filters_resolves_value_only_governed_categorical_filter():
    entities = [{
        "name": "Product",
        "synonyms": ["item"],
        "attributes": [{
            "name": "Color",
            "column_name": "Color",
            "synonyms": ["colour"],
            "semantic_type": "category",
        }],
    }]

    filters = QueryOrchestrator._required_filters(
        "Show revenue for red products", entities, []
    )

    assert filters == [{
        "attribute": "Color",
        "column_name": "Color",
        "operator": "=",
        "value": "red",
    }]


def test_required_filters_preserves_resolver_filters_without_duplicates():
    from datapilot.domain.semantic import ResolvedFilter

    existing = ResolvedFilter(
        attribute="Color",
        column_name="Color",
        operator="=",
        value="Red",
        confidence=0.9,
        source_text="Color Red",
    )
    entities = [{
        "name": "Product",
        "attributes": [{
            "name": "Color",
            "column_name": "Color",
            "semantic_type": "category",
        }],
    }]

    filters = QueryOrchestrator._required_filters(
        "Show red products", entities, [existing]
    )

    assert len(filters) == 1
    assert filters[0]["column_name"] == "Color"
    assert filters[0]["value"] == "Red"


def test_required_grouping_columns_treats_by_metric_as_ranking():
    entities = [
        {
            "name": "Customer",
            "synonyms": ["buyer"],
            "display_column": "CustomerID",
            "key_column": "CustomerID",
            "attributes": [],
        },
        {
            "name": "Sales Order",
            "display_column": "SalesOrderID",
            "key_column": "SalesOrderID",
            "attributes": [],
        },
    ]
    metrics = [{"name": "Order Count", "synonyms": ["number of orders"]}]

    assert QueryOrchestrator._required_grouping_columns(
        "Show top 10 customers by order count", entities, metrics=metrics
    ) == ["CustomerID"]
    assert QueryOrchestrator._required_grouping_columns(
        "Show top 10 buyers by order count", entities, metrics=metrics
    ) == ["CustomerID"]


def test_required_grouping_columns_composes_entity_and_attribute_terms():
    entities = [{
        "name": "Product",
        "synonyms": ["item"],
        "display_column": "Name",
        "key_column": "ProductID",
        "attributes": [{
            "name": "Color",
            "column_name": "Color",
            "synonyms": ["colour"],
        }],
    }]

    assert QueryOrchestrator._required_grouping_columns(
        "Show top 10 products by product colour", entities
    ) == ["Color"]
    assert QueryOrchestrator._required_grouping_columns(
        "Show top 10 items by item colour", entities
    ) == ["Color"]


def test_required_grouping_columns_uses_exact_metric_ranking_clause_with_multiple_metrics():
    entities = [
        {
            "name": "Customer",
            "synonyms": ["buyer"],
            "display_column": "CustomerID",
            "key_column": "CustomerID",
        },
        {
            "name": "Sales Order",
            "synonyms": ["order"],
            "display_column": "SalesOrderID",
            "key_column": "SalesOrderID",
        },
    ]
    metrics = [
        {"name": "Order Count", "synonyms": []},
        {"name": "Average Order Value", "synonyms": []},
    ]

    assert QueryOrchestrator._required_grouping_columns(
        "Show order count and average order value for top 10 customers by order count",
        entities,
        metrics=metrics,
    ) == ["CustomerID"]
    assert QueryOrchestrator._required_grouping_columns(
        "Show order count and average order value for top 10 buyers by order count",
        entities,
        metrics=metrics,
    ) == ["CustomerID"]

    # Entity vocabulary embedded inside metric phrases must not become grouping.
    assert QueryOrchestrator._required_grouping_columns(
        "Show average order value for top 10 buyers by order count",
        entities,
        metrics=metrics,
    ) == ["CustomerID"]


@pytest.mark.asyncio
async def test_invalid_metric_clarification_selection_is_rejected_before_generation():
    generator = FakeSQLGenerator()
    orchestrator = QueryOrchestrator(
        FakeDatabase(),
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
        semantic_retriever=FakeSemanticRetriever(),
        semantic_context_assembler=FakeSemanticContextAssembler(),
    )

    response = await orchestrator.query(QueryRequest(
        question="Show sales",
        source_name="AdventureWorks",
        clarification_selections={"metric": "Profit"},
    ))

    assert response.status == "rejected"
    assert response.sql is None
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_invalid_attribute_clarification_selection_is_rejected_before_generation():
    generator = FakeSQLGenerator()
    orchestrator = QueryOrchestrator(
        FakeDatabase(),
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
        semantic_retriever=FakeSemanticRetriever(),
        semantic_context_assembler=FakeAttributeSemanticContextAssembler(),
    )

    response = await orchestrator.query(QueryRequest(
        question="Show customers by region",
        source_name="AdventureWorks",
        clarification_selections={"attribute": "Customer.Secret Region"},
    ))

    assert response.status == "rejected"
    assert response.sql is None
    assert generator.calls == 0


def test_required_grouping_columns_resolves_multiple_attributes_on_same_entity():
    entities = [{
        "name": "Customer",
        "synonyms": ["buyer"],
        "display_column": "customer_name",
        "key_column": "customer_id",
        "attributes": [
            {
                "name": "Country",
                "column_name": "country",
                "synonyms": ["nation"],
            },
            {
                "name": "Segment",
                "column_name": "segment",
                "synonyms": ["customer segment"],
            },
        ],
    }]

    assert QueryOrchestrator._required_grouping_columns(
        "Show revenue by customer country and customer segment",
        entities,
    ) == ["country", "segment"]


def test_required_grouping_columns_resolves_attributes_across_entities():
    entities = [
        {
            "name": "Customer",
            "synonyms": ["buyer"],
            "display_column": "customer_name",
            "key_column": "customer_id",
            "attributes": [{
                "name": "Country",
                "column_name": "country",
                "synonyms": ["nation"],
            }],
        },
        {
            "name": "Product",
            "synonyms": ["item"],
            "display_column": "product_name",
            "key_column": "product_id",
            "attributes": [{
                "name": "Category",
                "column_name": "category",
                "synonyms": ["product category"],
            }],
        },
    ]

    assert QueryOrchestrator._required_grouping_columns(
        "Show revenue by product category and customer country",
        entities,
    ) == ["country", "category"]


@pytest.mark.asyncio
async def test_orchestrator_blocks_partial_multi_dimension_sql_before_execution():
    database = FakeDatabase()
    generator = FakeSQLGenerator(
        'SELECT country, SUM(amount) FROM records GROUP BY country'
    )
    orchestrator = QueryOrchestrator(
        database,
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
    )

    with pytest.raises(SQLValidationError) as error:
        await orchestrator._validate_and_execute(
            question="Show revenue by customer country and customer segment",
            sql=generator.sql,
            source="generator",
            confidence=1.0,
            required_grouping_columns=["country", "segment"],
        )

    assert "governed correctness" in str(error.value).lower()
    assert database.executed == []
    details = error.value.details
    failed_checks = details["checks"]
    violation = next(
        check for check in failed_checks
        if check["code"] == "grouping_dimension_violation"
    )
    assert violation["missing_columns"] == ["segment"]


@pytest.mark.asyncio
async def test_orchestrator_blocks_wrong_governed_time_sql_before_execution():
    database = FakeDatabase()
    generator = FakeSQLGenerator(
        """SELECT DATE_TRUNC('year', created_at), SUM(amount)
           FROM public.orders
           WHERE created_at >= DATE '2026-02-01'
             AND created_at < DATE '2027-01-01'
           GROUP BY DATE_TRUNC('year', created_at)"""
    )
    orchestrator = QueryOrchestrator(
        database,
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
    )
    time_plan = {
        "status": "resolved",
        "time_dimension": "Order Date",
        "entity": "Order",
        "schema_name": "public",
        "table_name": "orders",
        "column_name": "order_date",
        "role": "order_date",
        "source_grain": "day",
        "timezone": "UTC",
        "grouping_grain": "month",
        "comparison": False,
        "start": "2026-01-01",
        "end_exclusive": "2027-01-01",
    }

    with pytest.raises(SQLValidationError) as error:
        await orchestrator._validate_and_execute(
            question="Show monthly revenue this year",
            sql=generator.sql,
            source="generator",
            confidence=1.0,
            governed_tables=["public.orders"],
            required_time_plan=time_plan,
        )

    assert database.executed == []
    failed_checks = error.value.details["checks"]
    assert any(
        check["code"] == "time_filter_violation"
        and check["status"] == "failed"
        for check in failed_checks
    )
    assert any(
        check["code"] == "time_grain_violation"
        and check["status"] == "failed"
        for check in failed_checks
    )


class FailingSemanticRetriever:
    async def search(self, source_name, question, limit):
        raise RuntimeError("vector backend unavailable")


@pytest.mark.asyncio
async def test_semantic_retrieval_failure_is_wrapped_at_orchestrator_boundary():
    generator = FakeSQLGenerator()
    database = FakeDatabase()
    orchestrator = QueryOrchestrator(
        database,
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
        semantic_retriever=FailingSemanticRetriever(),
    )

    with pytest.raises(SemanticRetrievalError) as error:
        await orchestrator.query(
            QueryRequest(question="Show records", source_name="Commerce")
        )

    assert isinstance(error.value.__cause__, RuntimeError)
    assert error.value.details["source_name"] == "Commerce"
    assert generator.calls == 0
    assert database.executed == []


@pytest.mark.asyncio
async def test_time_interpretation_failure_is_wrapped_before_generation(monkeypatch):
    generator = FakeSQLGenerator()
    database = FakeDatabase()
    orchestrator = QueryOrchestrator(
        database,
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
    )

    def fail_time_resolution(question, dimensions):
        raise ValueError("invalid governed time metadata")

    monkeypatch.setattr(
        "datapilot.application.services.query_orchestrator.resolve_time_semantics",
        fail_time_resolution,
    )

    with pytest.raises(TimeInterpretationError) as error:
        await orchestrator.query(QueryRequest(question="Show records"))

    assert isinstance(error.value.__cause__, ValueError)
    assert generator.calls == 0
    assert database.executed == []


@pytest.mark.asyncio
async def test_orchestrator_fails_closed_when_required_correctness_is_unverifiable(monkeypatch):
    database = FakeDatabase()
    generator = FakeSQLGenerator("SELECT COUNT(*) AS count FROM records")
    orchestrator = QueryOrchestrator(
        database,
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
    )

    monkeypatch.setattr(
        "datapilot.application.services.query_orchestrator.assess_query_correctness",
        lambda **kwargs: [{
            "code": "relationship_verification_unavailable",
            "status": "skipped",
            "severity": "info",
            "message": "verification unavailable",
        }],
    )

    with pytest.raises(SQLValidationError) as error:
        await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert error.value.details["checks"][0]["code"] == "relationship_verification_unavailable"
    assert database.executed == []


@pytest.mark.asyncio
async def test_orchestrator_does_not_fail_closed_for_non_required_scope_skip(monkeypatch):
    database = FakeDatabase()
    generator = FakeSQLGenerator("SELECT COUNT(*) AS count FROM records")
    orchestrator = QueryOrchestrator(
        database,
        FakeValidator(),
        generator,
        FakeCatalog(SemanticCatalog()),
    )

    monkeypatch.setattr(
        "datapilot.application.services.query_orchestrator.assess_query_correctness",
        lambda **kwargs: [{
            "code": "governed_scope_unavailable",
            "status": "skipped",
            "severity": "info",
            "message": "no governed scope",
        }],
    )

    response = await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert response.status == "completed"
    assert database.executed


class SequencedSQLGenerator(FakeSQLGenerator):
    def __init__(self, sqls):
        super().__init__(sqls[0])
        self.sqls = list(sqls)

    async def generate(self, question, schema, context=None, dialect=None):
        self.calls += 1
        assert context is not None
        self.contexts.append(context)
        return self.sqls[min(self.calls - 1, len(self.sqls) - 1)]


@pytest.mark.asyncio
async def test_orchestrator_attempts_one_correction_for_recoverable_governed_failure(monkeypatch):
    database = FakeDatabase()
    generator = SequencedSQLGenerator([
        "SELECT wrong FROM records",
        "SELECT COUNT(*) AS count FROM records",
    ])
    orchestrator = QueryOrchestrator(
        database, FakeValidator(), generator, FakeCatalog(SemanticCatalog())
    )
    calls = {"count": 0}

    def correctness(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return [{
                "code": "grouping_dimension_violation",
                "status": "failed",
                "severity": "error",
                "message": "required grouping missing",
            }]
        return [{
            "code": "grouping_dimension_alignment",
            "status": "passed",
            "severity": "info",
        }]

    monkeypatch.setattr(
        "datapilot.application.services.query_orchestrator.assess_query_correctness",
        correctness,
    )

    response = await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert response.status == "completed"
    assert generator.calls == 2
    assert len(generator.contexts) == 2
    correction = generator.contexts[1]["sql_correction"]
    assert correction["attempt"] == 1
    assert correction["max_attempts"] == 1
    assert correction["failed_sql"] == "SELECT wrong FROM records"
    assert correction["feedback"][0]["code"] == "grouping_dimension_violation"
    assert response.trace is not None
    assert len(response.trace.correction_attempts) == 1
    assert database.executed == [response.sql]


@pytest.mark.asyncio
async def test_orchestrator_does_not_retry_after_corrected_sql_fails(monkeypatch):
    database = FakeDatabase()
    generator = SequencedSQLGenerator([
        "SELECT wrong FROM records",
        "SELECT still_wrong FROM records",
        "SELECT COUNT(*) AS count FROM records",
    ])
    orchestrator = QueryOrchestrator(
        database, FakeValidator(), generator, FakeCatalog(SemanticCatalog())
    )

    monkeypatch.setattr(
        "datapilot.application.services.query_orchestrator.assess_query_correctness",
        lambda **kwargs: [{
            "code": "filter_violation",
            "status": "failed",
            "severity": "error",
            "message": "required filter missing",
        }],
    )

    with pytest.raises(SQLValidationError):
        await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert generator.calls == 2
    assert database.executed == []


@pytest.mark.asyncio
async def test_orchestrator_does_not_correct_unverifiable_governed_failure(monkeypatch):
    database = FakeDatabase()
    generator = SequencedSQLGenerator([
        "SELECT wrong FROM records",
        "SELECT COUNT(*) AS count FROM records",
    ])
    orchestrator = QueryOrchestrator(
        database, FakeValidator(), generator, FakeCatalog(SemanticCatalog())
    )

    monkeypatch.setattr(
        "datapilot.application.services.query_orchestrator.assess_query_correctness",
        lambda **kwargs: [{
            "code": "relationship_verification_unavailable",
            "status": "skipped",
            "severity": "info",
            "message": "verification unavailable",
        }],
    )

    with pytest.raises(SQLValidationError):
        await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert generator.calls == 1
    assert database.executed == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first_code,second_code",
    [
        ("physical_scope_violation", "physical_scope_alignment"),
        ("relationship_violation", "relationship_alignment"),
        ("join_fanout_violation", "join_fanout_alignment"),
        ("time_filter_violation", "time_filter_alignment"),
        ("time_grain_violation", "time_grain_alignment"),
        ("time_comparison_violation", "time_comparison_alignment"),
    ],
)
async def test_bounded_correction_rechecks_stage_a_governed_invariants(
    monkeypatch, first_code, second_code
):
    database = FakeDatabase()
    generator = SequencedSQLGenerator([
        "SELECT wrong FROM records",
        "SELECT COUNT(*) AS count FROM records",
    ])
    orchestrator = QueryOrchestrator(
        database, FakeValidator(), generator, FakeCatalog(SemanticCatalog())
    )
    calls = {"count": 0}

    def correctness(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return [{
                "code": first_code,
                "status": "failed",
                "severity": "error",
                "message": "first proposal violates governed correctness",
            }]
        return [{
            "code": second_code,
            "status": "passed",
            "severity": "info",
            "message": "corrected proposal aligns",
        }]

    monkeypatch.setattr(
        "datapilot.application.services.query_orchestrator.assess_query_correctness",
        correctness,
    )

    response = await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert calls["count"] == 2
    assert generator.calls == 2
    assert database.executed == [response.sql]
    assert response.trace is not None
    assert response.trace.correction_attempts[0]["feedback"][0]["code"] == first_code
    assert response.trace.correctness_checks[0]["code"] == second_code


@pytest.mark.asyncio
async def test_corrected_sql_must_pass_safety_validation_before_execution(monkeypatch):
    from datapilot.domain.models import SQLValidationResult

    class SecondAttemptInvalidValidator:
        def __init__(self):
            self.calls = 0

        async def validate(self, sql, dialect=None, enforce_read_only=True):
            self.calls += 1
            if self.calls == 2:
                return SQLValidationResult(
                    is_valid=False,
                    is_read_only=False,
                    sanitized_sql=None,
                    errors=["corrected SQL is unsafe"],
                )
            return SQLValidationResult(
                is_valid=True,
                is_read_only=True,
                sanitized_sql=sql,
            )

    database = FakeDatabase()
    generator = SequencedSQLGenerator([
        "SELECT wrong FROM records",
        "DELETE FROM records",
    ])
    validator = SecondAttemptInvalidValidator()
    orchestrator = QueryOrchestrator(
        database, validator, generator, FakeCatalog(SemanticCatalog())
    )
    calls = {"count": 0}

    def correctness(**kwargs):
        calls["count"] += 1
        return [{
            "code": "filter_violation",
            "status": "failed",
            "severity": "error",
            "message": "required filter missing",
        }]

    monkeypatch.setattr(
        "datapilot.application.services.query_orchestrator.assess_query_correctness",
        correctness,
    )

    with pytest.raises(SQLValidationError):
        await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert generator.calls == 2
    assert validator.calls == 2
    assert database.executed == []


class RecoverableExecutionDatabase(FakeDatabase):
    def __init__(self, fail_every_time=False):
        super().__init__()
        self.fail_every_time = fail_every_time
        self.attempts = 0

    async def execute_query(self, sql: str, params=None, timeout_seconds=None):
        self.attempts += 1
        self.executed.append(sql)
        if self.attempts == 1 or self.fail_every_time:
            raise DatabaseExecutionError(
                "PostgreSQL query execution failed",
                details={
                    "provider": "postgresql",
                    "sqlstate": "42703",
                    "column_name": "missing",
                    "sql": sql,
                },
            )
        return await super().execute_query(sql, params, timeout_seconds)


class TerminalExecutionDatabase(FakeDatabase):
    async def execute_query(self, sql: str, params=None, timeout_seconds=None):
        self.executed.append(sql)
        raise DatabaseExecutionError(
            "PostgreSQL query execution failed",
            details={"provider": "postgresql", "sqlstate": "57014", "sql": sql},
        )


@pytest.mark.asyncio
async def test_orchestrator_attempts_one_recovery_for_recoverable_execution_error():
    database = RecoverableExecutionDatabase()
    generator = SequencedSQLGenerator([
        "SELECT missing FROM records",
        "SELECT COUNT(*) AS count FROM records",
    ])
    orchestrator = QueryOrchestrator(
        database, FakeValidator(), generator, FakeCatalog(SemanticCatalog())
    )

    response = await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert response.status == "completed"
    assert generator.calls == 2
    assert database.attempts == 2
    assert len(response.trace.execution_recovery_attempts) == 1
    attempt = response.trace.execution_recovery_attempts[0]
    assert attempt["database_error"]["sqlstate"] == "42703"
    assert attempt["classification"]["recoverable"] is True
    assert generator.contexts[1]["execution_recovery"]["failed_sql"].endswith("FROM records")


@pytest.mark.asyncio
async def test_orchestrator_does_not_retry_second_execution_failure():
    database = RecoverableExecutionDatabase(fail_every_time=True)
    generator = SequencedSQLGenerator([
        "SELECT missing FROM records",
        "SELECT still_missing FROM records",
        "SELECT COUNT(*) AS count FROM records",
    ])
    orchestrator = QueryOrchestrator(
        database, FakeValidator(), generator, FakeCatalog(SemanticCatalog())
    )

    with pytest.raises(DatabaseExecutionError):
        await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert generator.calls == 2
    assert database.attempts == 2


@pytest.mark.asyncio
async def test_orchestrator_does_not_recover_terminal_execution_error():
    database = TerminalExecutionDatabase()
    generator = SequencedSQLGenerator([
        "SELECT id FROM records",
        "SELECT COUNT(*) AS count FROM records",
    ])
    orchestrator = QueryOrchestrator(
        database, FakeValidator(), generator, FakeCatalog(SemanticCatalog())
    )

    with pytest.raises(DatabaseExecutionError):
        await orchestrator.query(QueryRequest(question="show records"))

    assert generator.calls == 1
    assert len(database.executed) == 1


@pytest.mark.asyncio
async def test_execution_recovery_sql_must_repass_safety_validation():
    from datapilot.domain.models import SQLValidationResult

    class RejectSecondValidation:
        def __init__(self):
            self.calls = 0

        async def validate(self, sql, dialect=None, enforce_read_only=True):
            self.calls += 1
            if self.calls == 2:
                return SQLValidationResult(
                    is_valid=False,
                    is_read_only=False,
                    sanitized_sql=None,
                    errors=["unsafe corrected SQL"],
                )
            return SQLValidationResult(
                is_valid=True,
                is_read_only=True,
                sanitized_sql=sql,
            )

    database = RecoverableExecutionDatabase()
    generator = SequencedSQLGenerator([
        "SELECT missing FROM records",
        "DELETE FROM records",
    ])
    validator = RejectSecondValidation()
    orchestrator = QueryOrchestrator(
        database, validator, generator, FakeCatalog(SemanticCatalog())
    )

    with pytest.raises(SQLValidationError):
        await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert generator.calls == 2
    assert database.attempts == 1
    assert validator.calls == 2


@pytest.mark.asyncio
async def test_execution_recovery_sql_must_repass_governed_correctness(monkeypatch):
    database = RecoverableExecutionDatabase()
    generator = SequencedSQLGenerator([
        "SELECT missing FROM records",
        "SELECT still_semantically_wrong FROM records",
        "SELECT COUNT(*) AS count FROM records",
    ])
    orchestrator = QueryOrchestrator(
        database, FakeValidator(), generator, FakeCatalog(SemanticCatalog())
    )
    calls = {"count": 0}

    def correctness(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return []
        return [{
            "code": "relationship_violation",
            "status": "failed",
            "severity": "error",
            "message": "recovered SQL violates governed relationship",
        }]

    monkeypatch.setattr(
        "datapilot.application.services.query_orchestrator.assess_query_correctness",
        correctness,
    )

    with pytest.raises(SQLValidationError):
        await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert generator.calls == 2
    assert database.attempts == 1
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_b1_correction_can_have_at_most_one_independent_b2_recovery(monkeypatch):
    database = RecoverableExecutionDatabase()
    generator = SequencedSQLGenerator([
        "SELECT governed_wrong FROM records",
        "SELECT execution_wrong FROM records",
        "SELECT COUNT(*) AS count FROM records",
    ])
    orchestrator = QueryOrchestrator(
        database, FakeValidator(), generator, FakeCatalog(SemanticCatalog())
    )
    calls = {"count": 0}

    def correctness(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return [{
                "code": "filter_violation",
                "status": "failed",
                "severity": "error",
                "message": "required governed filter missing",
            }]
        return [{
            "code": "filter_alignment",
            "status": "passed",
            "severity": "info",
        }]

    monkeypatch.setattr(
        "datapilot.application.services.query_orchestrator.assess_query_correctness",
        correctness,
    )

    response = await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert response.status == "completed"
    assert generator.calls == 3
    assert database.attempts == 2
    assert len(response.trace.correction_attempts) == 1
    assert len(response.trace.execution_recovery_attempts) == 1
    assert "sql_correction" in generator.contexts[1]
    assert "execution_recovery" in generator.contexts[2]


@pytest.mark.asyncio
async def test_b1_then_b2_second_database_failure_is_terminal(monkeypatch):
    database = RecoverableExecutionDatabase(fail_every_time=True)
    generator = SequencedSQLGenerator([
        "SELECT governed_wrong FROM records",
        "SELECT execution_wrong FROM records",
        "SELECT still_execution_wrong FROM records",
        "SELECT COUNT(*) AS count FROM records",
    ])
    orchestrator = QueryOrchestrator(
        database, FakeValidator(), generator, FakeCatalog(SemanticCatalog())
    )
    calls = {"count": 0}

    def correctness(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return [{
                "code": "physical_scope_violation",
                "status": "failed",
                "severity": "error",
                "message": "outside governed physical scope",
            }]
        return [{
            "code": "physical_scope_alignment",
            "status": "passed",
            "severity": "info",
        }]

    monkeypatch.setattr(
        "datapilot.application.services.query_orchestrator.assess_query_correctness",
        correctness,
    )

    with pytest.raises(DatabaseExecutionError):
        await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert generator.calls == 3
    assert database.attempts == 2


@pytest.mark.asyncio
async def test_execution_recovery_failure_does_not_start_b1_correction(monkeypatch):
    database = RecoverableExecutionDatabase()
    generator = SequencedSQLGenerator([
        "SELECT execution_wrong FROM records",
        "SELECT governed_wrong_after_recovery FROM records",
        "SELECT should_never_be_generated FROM records",
    ])
    orchestrator = QueryOrchestrator(
        database, FakeValidator(), generator, FakeCatalog(SemanticCatalog())
    )
    calls = {"count": 0}

    def correctness(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return []
        return [{
            "code": "time_grain_violation",
            "status": "failed",
            "severity": "error",
            "message": "execution-recovery SQL has wrong governed grain",
        }]

    monkeypatch.setattr(
        "datapilot.application.services.query_orchestrator.assess_query_correctness",
        correctness,
    )

    with pytest.raises(SQLValidationError):
        await orchestrator.query(QueryRequest(question="How many records exist?"))

    assert generator.calls == 2
    assert database.attempts == 1
