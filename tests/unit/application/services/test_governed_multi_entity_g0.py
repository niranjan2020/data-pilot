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
        "example", [], "show transaction count by region"
    )
    assert {e["name"] for e in context["entities"]} == {"Transaction", "Account"}
    assert {r["name"] for r in context["relationships"]} == {"Transaction to Account"}


class PublishedCatalog(Catalog):
    async def list_published_analytical_dimensions(self, source_id):
        return [{"entity_id": 2, "name": "Region", "column_name": "region",
                 "synonyms": ["territory"]}]


@pytest.mark.asyncio
async def test_published_dimension_adds_related_entity_and_relationship():
    context = await SemanticContextAssembler(PublishedCatalog()).assemble(
        "example", [], "show transaction count by region"
    )
    assert {e["name"] for e in context["entities"]} == {"Transaction", "Account"}
    assert {r["name"] for r in context["relationships"]} == {"Transaction to Account"}


@pytest.mark.asyncio
async def test_unpublished_near_name_does_not_add_related_entity():
    context = await SemanticContextAssembler(PublishedCatalog()).assemble(
        "example", [], "show transaction count by region_next"
    )
    assert {e["name"] for e in context["entities"]} == {"Transaction"}
    assert context["relationships"] == []


@pytest.mark.asyncio
async def test_follow_up_rehydrates_published_dimensions_from_authority():
    assembler = SemanticContextAssembler(PublishedCatalog())
    current = await assembler.assemble(
        "example", [], "show transaction count by region"
    )
    follow_up = await assembler.carry_forward(
        "example", current,
        {"previous_question": "show transaction count by region",
         "governed_entities": ["Transaction", "Account"],
         "governed_metrics": ["Transaction Count"]},
    )
    assert any(
        d["entity_id"] == 2 and d["column_name"] == "region"
        for d in follow_up["published_dimensions"]
    )


@pytest.mark.asyncio
async def test_follow_up_does_not_trust_injected_dimension_publications():
    assembler = SemanticContextAssembler(PublishedCatalog())
    current = await assembler.assemble("example", [], "show transactions")
    current["published_dimensions"] = [
        {"entity_id": 1, "name": "Fake", "column_name": "region_next"}
    ]
    follow_up = await assembler.carry_forward(
        "example", current,
        {"previous_question": "show transactions",
         "governed_entities": ["Transaction"]},
    )
    assert all(
        d["column_name"] != "region_next"
        for d in follow_up["published_dimensions"]
    )


def test_published_dimension_owners_do_not_match_identifier_prefix():
    from datapilot.application.services.semantic_context import (
        resolve_published_dimension_owners,
    )
    published = [{"entity_id": 2, "name": "Region",
                  "column_name": "region", "synonyms": []}]
    assert resolve_published_dimension_owners("count by region_next", published) == set()
    assert resolve_published_dimension_owners("count by region", published) == {2}


class MultiplePublishedDimensionsCatalog(PublishedCatalog):
    async def list_published_analytical_dimensions(self, source_id):
        return [
            {"entity_id": 2, "name": "Region", "column_name": "region",
             "synonyms": ["territory"]},
            {"entity_id": 99, "name": "Secret Category",
             "column_name": "secret_category", "synonyms": []},
        ]


@pytest.mark.asyncio
async def test_published_dimension_context_excludes_unselected_entity_grants():
    context = await SemanticContextAssembler(MultiplePublishedDimensionsCatalog()).assemble(
        "example", [], "show transaction count by region"
    )
    assert {d["column_name"] for d in context["published_dimensions"]} == {"region"}
    assert {e["name"] for e in context["entities"]} == {"Transaction", "Account"}


@pytest.mark.asyncio
async def test_published_dimension_contract_is_empty_for_unrelated_question():
    context = await SemanticContextAssembler(MultiplePublishedDimensionsCatalog()).assemble(
        "example", [], "show transactions"
    )
    assert context["published_dimensions"] == []
