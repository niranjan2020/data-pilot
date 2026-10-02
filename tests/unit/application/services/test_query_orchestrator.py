"""Tests for the provider-independent NL-to-SQL orchestration boundary."""

from __future__ import annotations

import pytest

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.domain.models import SchemaMetadata
from datapilot.domain.policies import QueryExecutionPolicy
from datapilot.domain.query import QueryRequest
from datapilot.domain.semantic import SemanticCatalog


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


