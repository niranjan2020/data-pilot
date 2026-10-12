"""G0 regression: cross-entity grouping must not silently lose its join context.

These tests use unrelated generic entity names, not any customer schema.
The first test records the current gap as an expected failure until the
published-dimension binder is integrated with semantic context expansion.
"""
import pytest

from datapilot.application.services.semantic_context import SemanticContextAssembler


class Catalog:
    async def get_data_source_id(self, name):
        return 7

    async def list_semantic_datasets(self, source_id):
        return []

    async def list_semantic_entities(self, source_id):
        return [
            {"id": 1, "name": "Transaction", "schema_name": "public",
             "table_name": "transactions", "synonyms": ["transactions"]},
            {"id": 2, "name": "Account", "schema_name": "public",
             "table_name": "accounts", "synonyms": ["accounts"]},
        ]

    async def list_semantic_relationships(self, source_id):
        return [
            {"id": 3, "name": "Transaction to Account",
             "from_entity_id": 1, "to_entity_id": 2,
             "from_column": "account_id", "to_column": "id"},
        ]

    async def list_semantic_metrics(self, source_id):
        return [
            {"id": 4, "name": "Transaction Count", "entity_id": 1,
             "synonyms": ["transaction count"]},
        ]

    async def list_business_rules(self, source_id):
        return []

    async def list_time_dimensions(self, source_id):
        return []


@pytest.mark.asyncio
async def test_explicit_related_entities_retain_join_context():
    context = await SemanticContextAssembler(Catalog()).assemble(
        "example", [], "show transaction count by account"
    )
    assert {e["name"] for e in context["entities"]} == {"Transaction", "Account"}
    assert {r["name"] for r in context["relationships"]} == {"Transaction to Account"}


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="G2/G3 pending: published dimension vocabulary does not yet anchor related entities",
)
async def test_metric_with_related_dimension_requires_join_context():
    # The question names the approved metric, and a dimension whose published
    # owning entity is Account; it does not name Account explicitly.
    # Current assembler cannot consume published attribute grants, so it
    # drops the Account entity and the relationship. A future implementation
    # must bind the dimension and include the approved path, or fail closed.
    context = await SemanticContextAssembler(Catalog()).assemble(
        "example", [], "show transaction count by account region"
    )
    assert {e["name"] for e in context["entities"]} == {"Transaction", "Account"}
    assert {r["name"] for r in context["relationships"]} == {"Transaction to Account"}
