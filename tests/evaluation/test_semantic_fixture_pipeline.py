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
            require_no_sql=True,
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
    assert response.explanation is not None
    assert response.explanation.outcome == "rejected"
    assert any(
        step.stage == "outcome" and step.status == "rejected"
        for step in response.explanation.steps
    )


@pytest.mark.asyncio
async def test_evaluation_fails_if_rejected_question_contains_sql():
    from datapilot.domain.query import QueryRejection, QueryResponse

    case = EvaluationCase(
        id="unsupported-must-not-generate-sql",
        question="What is the weather today?",
        expected=EvaluationExpectation(
            expected_status="rejected",
            rejection_code="unsupported_question",
            require_no_sql=True,
        ),
    )
    response = QueryResponse(
        question=case.question,
        status="rejected",
        sql="SELECT * FROM customers",
        rejection=QueryRejection(
            code="unsupported_question",
            reason="Question is outside the governed semantic domain.",
        ),
    )

    result = evaluate_query_response(case, response)

    assert not result.passed
    assert "sql_generation" in result.failure_categories
    assert "expected no generated SQL" in result.failures


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
    assert response.explanation is not None
    assert response.explanation.outcome == "dry_run"
    assert any(
        step.stage == "execution" and step.status == "not_executed"
        for step in response.explanation.steps
    )
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selection", "value", "expected_code"),
    [
        ("entity", "Missing Entity", "invalid_entity_selection"),
        ("metric", "Missing Metric", "invalid_metric_selection"),
        ("attribute", "Customer.Missing Attribute", "invalid_attribute_selection"),
        ("time_dimension", "Missing Date", "invalid_time_dimension_selection"),
    ],
)
async def test_invalid_semantic_selection_returns_structured_rejection(
    selection,
    value,
    expected_code,
):
    orchestrator = QueryOrchestrator(
        NoExecutionDatabase(),
        NoValidation(),
        NoGeneration(),
        FixtureCatalog(load_catalog()),
    )

    response = await orchestrator.query(
        QueryRequest(
            question="Show customers",
            clarification_selections={selection: value},
        )
    )

    assert response.status == "rejected"
    assert response.sql is None
    assert response.rejection is not None
    assert response.rejection.code == expected_code
    assert response.rejection.category == "semantic_resolution"
    assert response.rejection.retryable is False


class IrrelevantHighSimilarityRetriever:
    async def search(self, source_name, question, limit):
        return [
            {
                "kind": "entity",
                "name": "Customer",
                "score": 0.99,
                "metadata": {"id": 1},
            }
        ]


class MisleadingRetrievedContextAssembler:
    async def assemble(self, source_name, retrieved_context, question):
        # Simulate approximate retrieval returning a highly ranked governed object
        # for a question that contains no governed business vocabulary.
        return {
            "datasets": [
                {"schema_name": "public", "table_name": "customers", "name": "public.customers"}
            ],
            "entities": [
                {
                    "id": 1,
                    "name": "Customer",
                    "schema_name": "public",
                    "table_name": "customers",
                    "attributes": [],
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
async def test_irrelevant_retrieval_candidate_cannot_make_unsupported_question_executable():
    orchestrator = QueryOrchestrator(
        NoExecutionDatabase(),
        NoValidation(),
        NoGeneration(),
        FixtureCatalog(load_catalog()),
        semantic_retriever=IrrelevantHighSimilarityRetriever(),
        semantic_context_assembler=MisleadingRetrievedContextAssembler(),
    )

    response = await orchestrator.query(
        QueryRequest(
            question="What is the weather today?",
            source_name="Fixture",
        )
    )

    assert response.status == "rejected"
    assert response.sql is None
    assert response.rejection is not None
    assert response.rejection.code == "unsupported_question"
    assert response.trace is not None
    assert response.trace.governed_entities == ["Customer"]
