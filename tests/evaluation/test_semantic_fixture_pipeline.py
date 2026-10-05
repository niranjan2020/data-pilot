"""Deterministic evaluation of versioned semantic ambiguity fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.domain.models import SchemaMetadata
from datapilot.domain.query import QueryRequest
from datapilot.domain.semantic import SemanticCatalog
from tests.evaluation.harness import (
    EvaluationCase,
    EvaluationExpectation,
    evaluate_query_response,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "semantic" / "catalog.json"


class FixtureCatalog:
    def __init__(self, catalog: SemanticCatalog) -> None:
        self.catalog = catalog

    async def get_catalog(self) -> SemanticCatalog:
        return self.catalog


class NoExecutionDatabase:
    dialect = "postgresql"

    async def introspect_schema(self, schema_name=None):
        return SchemaMetadata(schema_name=schema_name, dialect=self.dialect)

    async def execute_query(self, *args, **kwargs):
        raise AssertionError("ambiguous evaluation must stop before database execution")


class NoValidation:
    async def validate(self, *args, **kwargs):
        raise AssertionError("ambiguous evaluation must stop before SQL validation")


class NoGeneration:
    async def generate(self, *args, **kwargs):
        raise AssertionError("ambiguous evaluation must stop before SQL generation")


def load_catalog() -> SemanticCatalog:
    return SemanticCatalog.model_validate(
        json.loads(FIXTURE.read_text(encoding="utf-8"))
    )


@pytest.mark.asyncio
async def test_versioned_fixture_entity_ambiguity_uses_real_orchestrator():
    case = EvaluationCase(
        id="account-entity-ambiguity",
        question="Show account",
        expected=EvaluationExpectation(
            expected_status="ambiguous",
            clarification_kind="entity",
            clarification_options=("Customer", "Order"),
        ),
    )
    orchestrator = QueryOrchestrator(
        NoExecutionDatabase(),
        NoValidation(),
        NoGeneration(),
        FixtureCatalog(load_catalog()),
    )

    response = await orchestrator.query(QueryRequest(question=case.question))
    result = evaluate_query_response(case, response)

    assert result.passed, result.failures
    assert response.sql is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "expected_status"),
    [
        ("Show account", "ambiguous"),
        ("What is the weather today?", "rejected"),
        ("Show employee salaries", "rejected"),
    ],
)
async def test_versioned_fixture_stops_before_sql_for_non_executable_semantics(
    question,
    expected_status,
):
    orchestrator = QueryOrchestrator(
        NoExecutionDatabase(),
        NoValidation(),
        NoGeneration(),
        FixtureCatalog(load_catalog()),
    )

    response = await orchestrator.query(QueryRequest(question=question))

    assert response.status == expected_status
    assert response.sql is None
