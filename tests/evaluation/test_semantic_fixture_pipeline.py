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
async def test_versioned_fixture_unsupported_question_returns_structured_rejection():
    case = EvaluationCase(
        id="unsupported-weather",
        question="What is the weather today?",
        expected=EvaluationExpectation(
            expected_status="rejected",
            rejection_code="unsupported_question",
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
    assert response.rejection is not None
    assert response.rejection.category == "semantic_resolution"
    assert response.rejection.retryable is False


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


class ResumeGenerator:
    def __init__(self) -> None:
        self.calls = 0
        self.contexts = []

    async def generate(self, question, schema, context=None, dialect=None):
        self.calls += 1
        self.contexts.append(context)
        return "SELECT COUNT(*) AS count FROM customers"


class PassValidation:
    async def validate(self, sql, dialect=None, enforce_read_only=True):
        from datapilot.domain.models import SQLValidationResult
        return SQLValidationResult(
            is_valid=True,
            is_read_only=True,
            sanitized_sql=sql,
            warnings=[],
        )


class ResumeDatabase(NoExecutionDatabase):
    async def execute_query(self, *args, **kwargs):
        raise AssertionError("dry-run clarification resume must not execute SQL")


@pytest.mark.asyncio
async def test_versioned_fixture_entity_clarification_resumes_real_orchestrator():
    generator = ResumeGenerator()
    orchestrator = QueryOrchestrator(
        ResumeDatabase(),
        PassValidation(),
        generator,
        FixtureCatalog(load_catalog()),
    )

    response = await orchestrator.query(
        QueryRequest(
            question="Show account",
            clarification_selections={"entity": "Customer"},
            dry_run=True,
        )
    )

    assert response.status == "dry_run"
    assert response.clarification is None
    assert response.resolved_intent is not None
    assert response.resolved_intent.entity is not None
    assert response.resolved_intent.entity.name == "Customer"
    assert generator.calls == 1
    assert generator.contexts[0]["clarification_selections"] == {
        "entity": "Customer"
    }
    assert response.trace is not None
    assert response.trace.clarification_selections == {"entity": "Customer"}


@pytest.mark.asyncio
@pytest.mark.parametrize("selected_entity", ["Employee", "Supplier", "Customer Account"])
async def test_versioned_fixture_rejects_unknown_entity_clarification_selection(
    selected_entity,
):
    orchestrator = QueryOrchestrator(
        NoExecutionDatabase(),
        NoValidation(),
        NoGeneration(),
        FixtureCatalog(load_catalog()),
    )

    response = await orchestrator.query(
        QueryRequest(
            question="Show account",
            clarification_selections={"entity": selected_entity},
        )
    )

    assert response.status == "rejected"
    assert response.sql is None
    assert response.clarification is None
    assert response.trace is not None
    assert response.trace.clarification_selections == {"entity": selected_entity}


@pytest.mark.asyncio
async def test_versioned_fixture_rejects_valid_but_conflicting_entity_selection():
    orchestrator = QueryOrchestrator(
        NoExecutionDatabase(),
        NoValidation(),
        NoGeneration(),
        FixtureCatalog(load_catalog()),
    )

    response = await orchestrator.query(
        QueryRequest(
            question="Show orders",
            clarification_selections={"entity": "Customer"},
        )
    )

    assert response.status == "rejected"
    assert response.sql is None
    assert response.resolved_intent is not None
    assert response.resolved_intent.entity is None


@pytest.mark.asyncio
async def test_current_entity_selection_overrides_stale_inherited_selection():
    generator = ResumeGenerator()
    orchestrator = QueryOrchestrator(
        ResumeDatabase(),
        PassValidation(),
        generator,
        FixtureCatalog(load_catalog()),
    )
    context = {
        "previous_question": "Show account",
        "clarification_selections": {"entity": "Order"},
    }

    response = await orchestrator.query(
        QueryRequest(
            question="Show account",
            clarification_selections={"entity": "Customer"},
            dry_run=True,
        ),
        conversation_context=context,
    )

    assert response.status == "dry_run"
    assert response.resolved_intent is not None
    assert response.resolved_intent.entity is not None
    assert response.resolved_intent.entity.name == "Customer"
    assert response.trace is not None
    assert response.trace.clarification_selections == {"entity": "Customer"}
    assert generator.calls == 1
