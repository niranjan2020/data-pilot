"""Tests for the provider-independent NL-to-SQL orchestration boundary."""

from __future__ import annotations

import pytest

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
        grouping = context.get("required_grouping_columns") or []
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
