"""Tests for the NL-to-SQL orchestration boundary."""

from __future__ import annotations

from typing import Any

import pytest

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.domain.query import QueryRequest, SQLGeneration
from datapilot.domain.semantic import QueryTemplate, SemanticCatalog


class FakeDatabase:
    dialect = "postgresql"

    def __init__(self) -> None:
        self.executed: list[str] = []

    async def introspect_schema(self):
        from datapilot.domain.models import SchemaMetadata
        return SchemaMetadata(dialect="postgresql")

    async def execute_query(self, sql: str, params=None, timeout_seconds=None):
        from datapilot.domain.models import QueryResult
        self.executed.append(sql)
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


class FakeLLM:
    provider_name = "fake"

    def __init__(self, sql: str = "SELECT COUNT(*) AS count FROM vessels") -> None:
        self.sql = sql
        self.calls = 0

    async def generate_structured(self, messages, response_schema, temperature=0.0, **kwargs):
        self.calls += 1
        assert response_schema is SQLGeneration
        return SQLGeneration(sql=self.sql, explanation="Generated from schema.")


class FakeCatalog:
    def __init__(self, catalog: SemanticCatalog) -> None:
        self.catalog = catalog

    async def get_catalog(self) -> SemanticCatalog:
        return self.catalog


@pytest.mark.asyncio
async def test_high_confidence_template_with_parameters_executes_without_llm():
    database = FakeDatabase()
    llm = FakeLLM()
    catalog = SemanticCatalog(
        templates=[
            QueryTemplate(
                name="VESSEL_BY_OPERATOR",
                description="Count vessels by operator",
                synonyms=["vessels by operator"],
                sql_template="SELECT COUNT(*) AS count FROM vessels WHERE operator = {{operator}}",
                required_parameters=["operator"],
            )
        ]
    )
    orchestrator = QueryOrchestrator(
        database,
        FakeValidator(),
        llm,
        FakeCatalog(catalog),
    )

    response = await orchestrator.query(
        QueryRequest(question="vessels by operator", parameters={"operator": "MSC"})
    )

    assert response.status == "completed"
    assert response.source == "template"
    assert response.matched_template == "VESSEL_BY_OPERATOR"
    assert response.sql.endswith("operator = 'MSC'")
    assert llm.calls == 0
    assert database.executed == [response.sql]


@pytest.mark.asyncio
async def test_ambiguous_match_does_not_execute_or_call_llm():
    database = FakeDatabase()
    llm = FakeLLM()
    catalog = SemanticCatalog(
        templates=[
            QueryTemplate(
                name="VESSEL_AGE",
                description="Average vessel age",
                synonyms=["average vessel"],
                sql_template="SELECT 1",
            ),
            QueryTemplate(
                name="VESSEL_AVAILABILITY",
                description="Vessel availability",
                synonyms=["average vessel"],
                sql_template="SELECT 1",
            ),
        ]
    )
    orchestrator = QueryOrchestrator(database, FakeValidator(), llm, FakeCatalog(catalog))

    response = await orchestrator.query(QueryRequest(question="average vessel"))

    assert response.status == "ambiguous"
    assert len(response.ambiguity_candidates) == 2
    assert database.executed == []
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_question_without_usable_template_uses_structured_llm():
    database = FakeDatabase()
    llm = FakeLLM("SELECT COUNT(*) AS count FROM vessels")
    orchestrator = QueryOrchestrator(
        database,
        FakeValidator(),
        llm,
        FakeCatalog(SemanticCatalog()),
    )

    response = await orchestrator.query(QueryRequest(question="How many vessels exist?"))

    assert response.status == "completed"
    assert response.source == "llm"
    assert response.sql == "SELECT COUNT(*) AS count FROM vessels"
    assert llm.calls == 1
    assert database.executed == [response.sql]


@pytest.mark.asyncio
async def test_template_missing_parameters_falls_back_to_llm():
    database = FakeDatabase()
    llm = FakeLLM("SELECT COUNT(*) AS count FROM vessels WHERE operator = 'MSC'")
    catalog = SemanticCatalog(
        templates=[
            QueryTemplate(
                name="VESSEL_BY_OPERATOR",
                description="Count vessels by operator",
                synonyms=["vessels by operator"],
                sql_template="SELECT COUNT(*) FROM vessels WHERE operator = {{operator}}",
                required_parameters=["operator"],
            )
        ]
    )
    orchestrator = QueryOrchestrator(database, FakeValidator(), llm, FakeCatalog(catalog))

    response = await orchestrator.query(
        QueryRequest(question="vessels by operator")
    )

    assert response.source == "llm"
    assert llm.calls == 1
