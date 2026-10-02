"""Tests for the provider-independent NL-to-SQL orchestration boundary."""

from __future__ import annotations

import pytest

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.domain.models import SchemaMetadata
from datapilot.domain.policies import QueryExecutionPolicy
from datapilot.domain.query import QueryRequest
from datapilot.domain.semantic import EntityAttributeDefinition, EntityDefinition, QueryTemplate, SemanticCatalog


class FakeDatabase:
    dialect = "generic"

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.timeouts: list[float | None] = []

    async def introspect_schema(self):
        return SchemaMetadata(dialect=self.dialect)

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
        assert dialect == "generic"
        assert context is not None
        assert "semantic_catalog" in context
        assert "query_intent" in context
        self.contexts.append(context)
        return self.sql


class FakeCatalog:
    def __init__(self, catalog: SemanticCatalog) -> None:
        self.catalog = catalog

    async def get_catalog(self) -> SemanticCatalog:
        return self.catalog


@pytest.mark.asyncio
async def test_template_with_explicit_parameters_executes_without_sql_generator():
    database = FakeDatabase()
    generator = FakeSQLGenerator()
    catalog = SemanticCatalog(
        templates=[
            QueryTemplate(
                name="RECORDS_BY_OWNER",
                description="Count records by owner",
                synonyms=["records by owner"],
                sql_template="SELECT COUNT(*) AS count FROM records WHERE owner = {{owner}}",
                required_parameters=["owner"],
            )
        ]
    )
    orchestrator = QueryOrchestrator(
        database, FakeValidator(), generator, FakeCatalog(catalog), query_timeout_seconds=12.0
    )

    response = await orchestrator.query(
        QueryRequest(question="records by owner", parameters={"owner": "Acme"})
    )

    assert response.source == "template"
    assert response.matched_template == "RECORDS_BY_OWNER"
    assert "owner = 'Acme'" in response.sql
    assert response.sql.endswith("LIMIT 1000")
    assert generator.calls == 0
    assert database.timeouts == [12.0]


@pytest.mark.asyncio
async def test_template_can_use_resolved_semantic_filter():
    database = FakeDatabase()
    generator = FakeSQLGenerator()
    catalog = SemanticCatalog(
        entities=[
            EntityDefinition(
                name="customer",
                synonyms=["customers"],
                table_name="customers",
                key_column="customer_id",
                attributes=[
                    EntityAttributeDefinition(
                        name="country", synonyms=["country"], column_name="country"
                    )
                ],
            )
        ],
        templates=[
            QueryTemplate(
                name="CUSTOMERS_BY_COUNTRY",
                description="Customers by country",
                synonyms=["customers by country"],
                sql_template="SELECT COUNT(*) FROM customers WHERE country = {{country}}",
                required_parameters=["country"],
            )
        ],
    )
    orchestrator = QueryOrchestrator(database, FakeValidator(), generator, FakeCatalog(catalog))

    response = await orchestrator.query(QueryRequest(question="customers in India"))

    assert response.source == "template"
    assert "country = 'India'" in response.sql
    assert response.sql.endswith("LIMIT 1000")
    assert response.resolved_intent is not None
    assert response.resolved_intent.filters[0].value == "India"
    assert generator.calls == 0


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


@pytest.mark.asyncio
async def test_ambiguous_template_match_does_not_execute_or_generate():
    database = FakeDatabase()
    generator = FakeSQLGenerator()
    catalog = SemanticCatalog(
        templates=[
            QueryTemplate(name="SALES_SUMMARY", description="Sales summary", synonyms=["summary"], sql_template="SELECT 1"),
            QueryTemplate(name="INVENTORY_SUMMARY", description="Inventory summary", synonyms=["summary"], sql_template="SELECT 1"),
        ]
    )
    orchestrator = QueryOrchestrator(database, FakeValidator(), generator, FakeCatalog(catalog))

    response = await orchestrator.query(QueryRequest(question="summary"))

    assert response.status == "ambiguous"
    assert len(response.ambiguity_candidates) == 2
    assert database.executed == []
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_template_missing_parameters_falls_back_to_generic_generator():
    database = FakeDatabase()
    generator = FakeSQLGenerator("SELECT COUNT(*) FROM records WHERE owner = 'Acme'")
    catalog = SemanticCatalog(
        templates=[
            QueryTemplate(
                name="RECORDS_BY_OWNER",
                description="Count records by owner",
                synonyms=["records by owner"],
                sql_template="SELECT COUNT(*) FROM records WHERE owner = {{owner}}",
                required_parameters=["owner"],
            )
        ]
    )
    orchestrator = QueryOrchestrator(database, FakeValidator(), generator, FakeCatalog(catalog))

    response = await orchestrator.query(QueryRequest(question="records by owner"))

    assert response.source == "generator"
    assert generator.calls == 1
