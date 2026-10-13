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
                "candidates": [
                    {"relationship_ids": [10, 11],
                     "relationship_names": ["Transaction Bridge", "Bridge Region"]},
                    {"relationship_ids": [12, 13],
                     "relationship_names": ["Transaction Alternate", "Alternate Region"]},
                ] if self.status == "ambiguous" else [],
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
    request = QueryRequest(question="show transaction count by region",
                           source_name="example")
    if status == "ambiguous":
        response = await orchestrator.query(
            request, conversation_context={"previous_question": "show transactions"},
        )
        assert response.status == "ambiguous"
        assert response.clarification is not None
        assert response.clarification.kind == "relationship"
        assert [option.value for option in response.clarification.options] == [
            "10,11", "12,13",
        ]
        assert [option.label for option in response.clarification.options] == [
            "Transaction Bridge → Bridge Region",
            "Transaction Alternate → Alternate Region",
        ]
        assert response.sql is None
    else:
        with pytest.raises(SQLValidationError) as caught:
            await orchestrator.query(
                request, conversation_context={"previous_question": "show transactions"},
            )
        checks = caught.value.details["checks"]
        assert checks[0]["code"] == "semantic_relationship_path_unresolved"
        assert checks[0]["reason"] == status
    assert assembler.assemble_calls == 1
    assert assembler.carry_calls == 1
    generator.generate.assert_not_awaited()
    database.execute_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_relationship_selection_cannot_bypass_publication_authorization():
    assembler = PathAssembler("ambiguous")
    generator = SimpleNamespace(
        generate=AsyncMock(side_effect=AssertionError("SQL generated")),
    )
    database = SimpleNamespace(
        dialect="postgres",
        execute_query=AsyncMock(side_effect=AssertionError("database executed")),
    )
    orchestrator = QueryOrchestrator(
        database_provider=database,
        sql_validator=Mock(),
        sql_generator=generator,
        semantic_catalog_provider=Mock(),
        semantic_context_assembler=assembler,
    )
    with pytest.raises(SQLValidationError, match="publication metadata is unavailable"):
        await orchestrator.query(QueryRequest(
            question="show transaction count by region",
            source_name="example",
            clarification_selections={"relationship": "10,11"},
        ))
    generator.generate.assert_not_awaited()
    database.execute_query.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["999", "10,12", "", "10,11,13"])
async def test_forged_or_stale_relationship_selection_is_rejected(selection):
    assembler = PathAssembler("ambiguous")
    generator = SimpleNamespace(
        generate=AsyncMock(side_effect=AssertionError("SQL generated")),
    )
    database = SimpleNamespace(
        dialect="postgres",
        execute_query=AsyncMock(side_effect=AssertionError("database executed")),
    )
    orchestrator = QueryOrchestrator(
        database_provider=database,
        sql_validator=Mock(),
        sql_generator=generator,
        semantic_catalog_provider=Mock(),
        semantic_context_assembler=assembler,
    )
    response = await orchestrator.query(QueryRequest(
        question="show transaction count by region",
        source_name="example",
        clarification_selections={"relationship": selection},
    ))
    assert response.status == "rejected"
    assert response.rejection is not None
    assert response.rejection.code == "invalid_relationship_selection"
    assert response.sql is None
    generator.generate.assert_not_awaited()
    database.execute_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_selected_path_requires_current_physical_publication_grants():
    assembler = PathAssembler("ambiguous")
    generator = SimpleNamespace(
        generate=AsyncMock(side_effect=AssertionError("SQL generated")),
    )
    database = SimpleNamespace(
        dialect="postgres",
        execute_query=AsyncMock(side_effect=AssertionError("database executed")),
    )
    metadata = SimpleNamespace(
        get_data_source_id=AsyncMock(return_value=42),
        list_semantic_entities=AsyncMock(return_value=[
            {"id": 1, "schema_name": "public", "table_name": "transactions"},
            {"id": 2, "schema_name": "public", "table_name": "bridges"},
            {"id": 3, "schema_name": "public", "table_name": "regions"},
        ]),
        list_semantic_relationships=AsyncMock(return_value=[
            {"id": 10, "from_entity_id": 1, "to_entity_id": 2,
             "from_column": "bridge_id", "to_column": "id"},
            {"id": 11, "from_entity_id": 2, "to_entity_id": 3,
             "from_column": "region_id", "to_column": "id"},
        ]),
        list_current_relationship_publications=AsyncMock(return_value=[]),
    )
    orchestrator = QueryOrchestrator(
        database_provider=database,
        sql_validator=Mock(),
        sql_generator=generator,
        semantic_catalog_provider=Mock(),
        semantic_context_assembler=assembler,
        relationship_publication_metadata=metadata,
    )
    with pytest.raises(SQLValidationError) as caught:
        await orchestrator.query(QueryRequest(
            question="show transaction count by region",
            source_name="example",
            clarification_selections={"relationship": "10,11"},
        ))
    assert caught.value.details["checks"][0]["code"] == "selected_relationship_not_published"
    metadata.list_current_relationship_publications.assert_awaited_once_with(42)
    generator.generate.assert_not_awaited()
    database.execute_query.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_edge", [
    {"id": 10, "from_entity_id": 1, "to_entity_id": 3,
     "from_column": "bridge_id", "to_column": "id"},
    {"id": 11, "from_entity_id": 2, "to_entity_id": 4,
     "from_column": "region_id", "to_column": "id"},
    {"id": 11, "from_entity_id": 4, "to_entity_id": 3,
     "from_column": "region_id", "to_column": "id"},
])
async def test_selected_route_rejects_repointed_or_disconnected_semantic_edges(changed_edge):
    base_edges = [
        {"id": 10, "from_entity_id": 1, "to_entity_id": 2,
         "from_column": "bridge_id", "to_column": "id"},
        {"id": 11, "from_entity_id": 2, "to_entity_id": 3,
         "from_column": "region_id", "to_column": "id"},
    ]
    edges = [changed_edge if edge["id"] == changed_edge["id"] else edge
             for edge in base_edges]
    metadata = SimpleNamespace(
        get_data_source_id=AsyncMock(return_value=42),
        list_semantic_entities=AsyncMock(return_value=[
            {"id": i, "schema_name": "public", "table_name": f"entity_{i}"}
            for i in range(1, 5)
        ]),
        list_semantic_relationships=AsyncMock(return_value=edges),
        list_current_relationship_publications=AsyncMock(return_value=[]),
    )
    generator = SimpleNamespace(
        generate=AsyncMock(side_effect=AssertionError("SQL generated")),
    )
    database = SimpleNamespace(
        dialect="postgres",
        execute_query=AsyncMock(side_effect=AssertionError("database executed")),
    )
    orchestrator = QueryOrchestrator(
        database_provider=database,
        sql_validator=Mock(),
        sql_generator=generator,
        semantic_catalog_provider=Mock(),
        semantic_context_assembler=PathAssembler("ambiguous"),
        relationship_publication_metadata=metadata,
    )
    with pytest.raises(SQLValidationError, match="Selected relationship path no longer"):
        await orchestrator.query(QueryRequest(
            question="show transaction count by region",
            source_name="example",
            clarification_selections={"relationship": "10,11"},
        ))
    generator.generate.assert_not_awaited()
    database.execute_query.assert_not_awaited()
