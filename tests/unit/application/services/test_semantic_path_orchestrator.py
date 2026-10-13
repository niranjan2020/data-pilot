"""Orchestrator must stop unresolved semantic paths before SQL generation."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.core.exceptions import SQLValidationError
from datapilot.domain.query import QueryRequest


class PathAssembler:
    def __init__(self, status):
        self.status = status
        self.assemble_calls = 0
        self.carry_calls = 0

    async def assemble(self, source, retrieved, question):
        self.assemble_calls += 1
        return {
            "datasets": [], "entities": [], "relationships": [],
            "metrics": [], "business_rules": [],
            "relationship_path_issues": [{
                "metric_entity_id": 1,
                "dimension_entity_id": 3,
                "status": self.status,
            }],
        }

    async def carry_forward(self, source, current, conversation):
        self.carry_calls += 1
        # Deliberately omit path issues, reproducing the follow-up hazard.
        return {key: value for key, value in current.items()
                if key != "relationship_path_issues"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ambiguous", "disconnected"])
async def test_unresolved_semantic_path_blocks_before_generator_or_database(status):
    assembler = PathAssembler(status)
    database = SimpleNamespace(
        dialect="postgres",
        execute_query=AsyncMock(side_effect=AssertionError("database executed")),
    )
    generator = SimpleNamespace(
        generate=AsyncMock(side_effect=AssertionError("SQL generated")),
    )
    orchestrator = QueryOrchestrator(
        database_provider=database,
        sql_validator=Mock(),
        sql_generator=generator,
        semantic_catalog_provider=Mock(),
        semantic_context_assembler=assembler,
    )
    with pytest.raises(SQLValidationError) as caught:
        await orchestrator.query(
            QueryRequest(question="show transaction count by region",
                         source_name="example"),
            conversation_context={"previous_question": "show transactions"},
        )
    checks = caught.value.details["checks"]
    assert checks[0]["code"] == "semantic_relationship_path_unresolved"
    assert checks[0]["reason"] == status
    assert assembler.assemble_calls == 1
    assert assembler.carry_calls == 1
    generator.generate.assert_not_awaited()
    database.execute_query.assert_not_awaited()
