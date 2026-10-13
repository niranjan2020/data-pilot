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


def test_unique_shortest_relationship_path_supports_two_hops():
    from datapilot.application.services.semantic_context import (
        unique_shortest_relationship_path,
    )
    edges = [
        {"id": 10, "from_entity_id": 1, "to_entity_id": 2},
        {"id": 11, "from_entity_id": 2, "to_entity_id": 3},
    ]
    assert [r["id"] for r in unique_shortest_relationship_path(1, 3, edges)] == [10, 11]


def test_unique_shortest_relationship_path_rejects_ambiguous_routes():
    from datapilot.application.services.semantic_context import (
        unique_shortest_relationship_path,
    )
    edges = [
        {"id": 10, "from_entity_id": 1, "to_entity_id": 2},
        {"id": 11, "from_entity_id": 2, "to_entity_id": 4},
        {"id": 12, "from_entity_id": 1, "to_entity_id": 3},
        {"id": 13, "from_entity_id": 3, "to_entity_id": 4},
    ]
    assert unique_shortest_relationship_path(1, 4, edges) == ()


class TwoHopCatalog(PublishedCatalog):
    async def list_semantic_entities(self, source_id):
        return [
            {"id": 1, "name": "Transaction", "schema_name": "public",
             "table_name": "transactions", "synonyms": ["transactions"]},
            {"id": 2, "name": "Bridge", "schema_name": "public",
             "table_name": "bridges", "synonyms": []},
            {"id": 3, "name": "Territory", "schema_name": "public",
             "table_name": "territories", "synonyms": []},
        ]

    async def list_semantic_relationships(self, source_id):
        return [
            {"id": 10, "name": "Transaction Bridge",
             "from_entity_id": 1, "to_entity_id": 2,
             "from_column": "bridge_id", "to_column": "id"},
            {"id": 11, "name": "Bridge Territory",
             "from_entity_id": 2, "to_entity_id": 3,
             "from_column": "territory_id", "to_column": "id"},
        ]

    async def list_published_analytical_dimensions(self, source_id):
        return [{"entity_id": 3, "name": "Region",
                 "column_name": "region", "synonyms": []}]


@pytest.mark.asyncio
async def test_metric_and_published_dimension_include_unique_two_hop_path():
    context = await SemanticContextAssembler(TwoHopCatalog()).assemble(
        "example", [], "show transaction count by region"
    )
    assert {e["id"] for e in context["entities"]} == {1, 2, 3}
    assert {r["id"] for r in context["relationships"]} == {10, 11}
    assert {d["table_name"] for d in context["datasets"]} == {
        "transactions", "bridges", "territories"
    }


class AmbiguousTwoHopCatalog(TwoHopCatalog):
    async def list_semantic_entities(self, source_id):
        return [
            *await super().list_semantic_entities(source_id),
            {"id": 4, "name": "Alternative Bridge", "schema_name": "public",
             "table_name": "alternative_bridges", "synonyms": []},
        ]

    async def list_semantic_relationships(self, source_id):
        return [
            *await super().list_semantic_relationships(source_id),
            {"id": 12, "name": "Transaction Alternative",
             "from_entity_id": 1, "to_entity_id": 4,
             "from_column": "alt_id", "to_column": "id"},
            {"id": 13, "name": "Alternative Territory",
             "from_entity_id": 4, "to_entity_id": 3,
             "from_column": "territory_id", "to_column": "id"},
        ]


@pytest.mark.asyncio
async def test_ambiguous_two_hop_path_does_not_select_bridge():
    context = await SemanticContextAssembler(AmbiguousTwoHopCatalog()).assemble(
        "example", [], "show transaction count by region"
    )
    assert {e["id"] for e in context["entities"]} == {1, 3}
    assert context["relationships"] == []


def test_shortest_relationship_path_preferred_over_longer_route():
    from datapilot.application.services.semantic_context import (
        unique_shortest_relationship_path,
    )
    edges = [
        {"id": 1, "from_entity_id": 1, "to_entity_id": 2},
        {"id": 2, "from_entity_id": 2, "to_entity_id": 3},
        {"id": 3, "from_entity_id": 1, "to_entity_id": 4},
        {"id": 4, "from_entity_id": 4, "to_entity_id": 5},
        {"id": 5, "from_entity_id": 5, "to_entity_id": 3},
    ]
    assert [r["id"] for r in unique_shortest_relationship_path(1, 3, edges)] == [1, 2]


def test_parallel_relationship_edges_are_ambiguous():
    from datapilot.application.services.semantic_context import (
        unique_shortest_relationship_path,
    )
    edges = [
        {"id": 1, "from_entity_id": 1, "to_entity_id": 2},
        {"id": 2, "from_entity_id": 1, "to_entity_id": 2},
    ]
    assert unique_shortest_relationship_path(1, 2, edges) == ()


def test_cycles_do_not_create_false_shortest_path_ambiguity():
    from datapilot.application.services.semantic_context import (
        unique_shortest_relationship_path,
    )
    edges = [
        {"id": 1, "from_entity_id": 1, "to_entity_id": 2},
        {"id": 2, "from_entity_id": 2, "to_entity_id": 3},
        {"id": 3, "from_entity_id": 3, "to_entity_id": 1},
        {"id": 4, "from_entity_id": 3, "to_entity_id": 4},
    ]
    assert [r["id"] for r in unique_shortest_relationship_path(1, 4, edges)] == [3, 4]


def test_disconnected_relationship_graph_has_no_path():
    from datapilot.application.services.semantic_context import (
        unique_shortest_relationship_path,
    )
    edges = [{"id": 1, "from_entity_id": 1, "to_entity_id": 2}]
    assert unique_shortest_relationship_path(1, 4, edges) == ()


@pytest.mark.asyncio
async def test_ambiguous_semantic_route_is_reported_without_guessing():
    context = await SemanticContextAssembler(AmbiguousTwoHopCatalog()).assemble(
        "example", [], "show transaction count by region"
    )
    issues = context["relationship_path_issues"]
    assert len(issues) == 1
    assert {key: issues[0][key] for key in (
        "metric_entity_id", "dimension_entity_id", "status"
    )} == {
        "metric_entity_id": 1, "dimension_entity_id": 3,
        "status": "ambiguous",
    }
    assert [candidate["relationship_ids"] for candidate in issues[0]["candidates"]] == [
        [10, 11], [12, 13],
    ]
    assert context["relationships"] == []


@pytest.mark.asyncio
async def test_unique_semantic_route_has_no_path_issue():
    context = await SemanticContextAssembler(TwoHopCatalog()).assemble(
        "example", [], "show transaction count by region"
    )
    assert context["relationship_path_issues"] == []


def test_semantic_route_classifies_disconnected_and_parallel_edges():
    from datapilot.application.services.semantic_context import classify_relationship_path
    assert classify_relationship_path(1, 3, [
        {"from_entity_id": 1, "to_entity_id": 2},
    ]) == "disconnected"
    assert classify_relationship_path(1, 2, [
        {"from_entity_id": 1, "to_entity_id": 2},
        {"from_entity_id": 1, "to_entity_id": 2},
    ]) == "ambiguous"
    assert classify_relationship_path(1, 1, []) == "same_entity"


def test_shortest_path_candidates_have_stable_ids_and_names():
    from datapilot.application.services.semantic_context import (
        shortest_relationship_path_candidates,
    )
    edges = [
        {"id": 12, "name": "Alternative first", "from_entity_id": 1, "to_entity_id": 4},
        {"id": 13, "name": "Alternative second", "from_entity_id": 4, "to_entity_id": 3},
        {"id": 10, "name": "First", "from_entity_id": 1, "to_entity_id": 2},
        {"id": 11, "name": "Second", "from_entity_id": 2, "to_entity_id": 3},
    ]
    routes = shortest_relationship_path_candidates(1, 3, edges)
    assert [[edge["id"] for edge in route] for route in routes] == [
        [10, 11], [12, 13],
    ]
    assert [[edge["id"] for edge in route] for route in
            shortest_relationship_path_candidates(1, 3, list(reversed(edges)))] == [
        [10, 11], [12, 13],
    ]


@pytest.mark.asyncio
async def test_ambiguous_path_context_contains_named_candidate_routes():
    context = await SemanticContextAssembler(AmbiguousTwoHopCatalog()).assemble(
        "example", [], "show transaction count by region"
    )
    issue, = context["relationship_path_issues"]
    assert issue["status"] == "ambiguous"
    assert [candidate["relationship_ids"] for candidate in issue["candidates"]] == [
        [10, 11], [12, 13],
    ]
    assert issue["candidates"][0]["relationship_names"] == [
        "Transaction Bridge", "Bridge Territory",
    ]


def test_path_candidates_do_not_use_unstable_or_duplicate_relationship_ids():
    from datapilot.application.services.semantic_context import (
        shortest_relationship_path_candidates,
    )
    assert shortest_relationship_path_candidates(1, 2, [
        {"from_entity_id": 1, "to_entity_id": 2},
    ]) == []
    assert shortest_relationship_path_candidates(1, 2, [
        {"id": 1, "from_entity_id": 1, "to_entity_id": 2},
        {"id": 1, "from_entity_id": 1, "to_entity_id": 2},
    ]) == []
