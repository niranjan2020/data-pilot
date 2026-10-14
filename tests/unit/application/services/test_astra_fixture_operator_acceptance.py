"""Astra-shaped acceptance contracts; synthetic metadata, not live Astra evidence.

The metric owner is Fixture; the requested grouping owner is Vessel.
Physical near-name columns are never publication grants.
"""
import pytest

from datapilot.application.services.semantic_context import SemanticContextAssembler
from datapilot.application.published_join_authorization import (
    authorize_exact_selected_route_sql,
)


class AstraFixtureCatalog:
    def __init__(self, *, operator_published=True, relationship_present=True):
        self.operator_published = operator_published
        self.relationship_present = relationship_present

    async def get_data_source_id(self, source):
        return 7

    async def list_semantic_datasets(self, source_id):
        return []

    async def list_semantic_entities(self, source_id):
        return [
            {"id": 1, "name": "Fixture", "schema_name": "astra",
             "table_name": "fixtures", "synonyms": ["fixtures"]},
            {"id": 2, "name": "Vessel", "schema_name": "astra",
             "table_name": "vessels", "synonyms": ["vessels"]},
        ]

    async def list_semantic_relationships(self, source_id):
        return ([{"id": 10, "name": "Fixture Vessel",
                  "from_entity_id": 1, "to_entity_id": 2,
                  "from_column": "vessel_id", "to_column": "id"}]
                if self.relationship_present else [])

    async def list_semantic_metrics(self, source_id):
        return [{"id": 20, "name": "Fixture Count", "entity_id": 1,
                 "synonyms": ["fixture count"]}]

    async def list_business_rules(self, source_id):
        return []

    async def list_time_dimensions(self, source_id):
        return []

    async def list_published_analytical_dimensions(self, source_id):
        return ([{"entity_id": 2, "name": "Operator",
                  "column_name": "operator", "synonyms": []}]
                if self.operator_published else [])


@pytest.mark.asyncio
async def test_fixture_count_by_published_vessel_operator_requires_vessel_path():
    context = await SemanticContextAssembler(AstraFixtureCatalog()).assemble(
        "astra", [], "Show fixture count by operator"
    )
    assert {metric["name"] for metric in context["metrics"]} == {"Fixture Count"}
    assert {entity["name"] for entity in context["entities"]} == {"Fixture", "Vessel"}
    assert [edge["id"] for edge in context["relationships"]] == [10]
    assert any(d["entity_id"] == 2 and d["column_name"] == "operator"
               for d in context["published_dimensions"])


@pytest.mark.asyncio
async def test_unpublished_operator_does_not_select_vessel_or_guess_operator_next():
    context = await SemanticContextAssembler(
        AstraFixtureCatalog(operator_published=False)
    ).assemble("astra", [], "Show fixture count by operator")
    assert not any(d.get("column_name") == "operator"
                   for d in context["published_dimensions"])
    assert not any(d.get("column_name") == "operator_next"
                   for d in context["published_dimensions"])
    assert not context["relationships"]


@pytest.mark.asyncio
async def test_missing_fixture_vessel_relationship_is_not_invented():
    context = await SemanticContextAssembler(
        AstraFixtureCatalog(relationship_present=False)
    ).assemble("astra", [], "Show fixture count by operator")
    assert not context["relationships"]
    assert context["relationship_path_issues"]
    assert context["relationship_path_issues"][0]["status"] == "disconnected"


def test_fixture_count_by_operator_rejects_physical_near_name_substitution():
    relationship = [{
        "from_schema": "astra", "from_table": "fixtures",
        "from_column": "vessel_id", "to_schema": "astra",
        "to_table": "vessels", "to_column": "id",
        "cardinality": "many_to_one", "join_policy": "preserve_source",
    }]
    approved_sql = (
        "SELECT v.operator, COUNT(DISTINCT f.id) AS fixture_count "
        "FROM astra.fixtures f LEFT JOIN astra.vessels v "
        "ON f.vessel_id = v.id GROUP BY v.operator"
    )
    wrong_sql = (
        "SELECT f.operator_next, COUNT(DISTINCT f.id) AS fixture_count "
        "FROM astra.fixtures f GROUP BY f.operator_next"
    )
    assert authorize_exact_selected_route_sql(approved_sql, relationship).allowed
    assert not authorize_exact_selected_route_sql(wrong_sql, relationship).allowed


@pytest.mark.asyncio
async def test_unpublished_operator_produces_explicit_no_sql_signal():
    context = await SemanticContextAssembler(
        AstraFixtureCatalog(operator_published=False)
    ).assemble("astra", [], "Show fixture count by operator")
    assert context["unpublished_grouping_intent"] == "operator"
    assert context["metrics"] == []


@pytest.mark.asyncio
async def test_published_operator_has_no_unpublished_dimension_signal():
    context = await SemanticContextAssembler(AstraFixtureCatalog()).assemble(
        "astra", [], "Show fixture count by operator"
    )
    assert "unpublished_grouping_intent" not in context


@pytest.mark.asyncio
async def test_ranked_metric_by_count_is_not_mistaken_for_grouping_dimension():
    """'operators by vessel count' is a ranking measure, not 'by vessel count' grouping."""
    catalog = AstraFixtureCatalog(operator_published=False)
    context = await SemanticContextAssembler(catalog).assemble(
        "astra", [], "Show the top 10 fixtures by fixture count"
    )
    assert "unpublished_grouping_intent" not in context


@pytest.mark.asyncio
async def test_local_grouping_with_following_qualifier_is_not_rejected():
    class LocalMetricCatalog(AstraFixtureCatalog):
        async def list_semantic_entities(self, source_id):
            return [{
                "id": 1, "name": "Fixture", "schema_name": "astra",
                "table_name": "fixtures", "synonyms": ["fixtures"],
                "attributes": [{"name": "Charterer", "column_name": "charterer"}],
            }]

    context = await SemanticContextAssembler(
        LocalMetricCatalog(operator_published=False)
    ).assemble("astra", [], "Show fixture count by charterer for the top 10 fixtures")
    assert "unpublished_grouping_intent" not in context


@pytest.mark.asyncio
async def test_unpublished_related_grouping_with_following_qualifier_still_rejected():
    context = await SemanticContextAssembler(
        AstraFixtureCatalog(operator_published=False)
    ).assemble("astra", [], "Show fixture count by operator for the top 10 fixtures")
    assert context["unpublished_grouping_intent"] == "operator"


@pytest.mark.asyncio
async def test_ranked_metric_with_qualifier_not_treated_as_grouping():
    context = await SemanticContextAssembler(
        AstraFixtureCatalog(operator_published=False)
    ).assemble("astra", [], "Show top 10 fixtures by fixture count for last month")
    assert "unpublished_grouping_intent" not in context


@pytest.mark.asyncio
async def test_same_entity_column_name_is_valid_grouping_alias():
    class LocalMetricCatalog(AstraFixtureCatalog):
        async def list_semantic_entities(self, source_id):
            return [{
                "id": 1, "name": "Fixture", "schema_name": "astra",
                "table_name": "fixtures", "synonyms": ["fixtures"],
                "attributes": [{
                    "name": "Charterer Company",
                    "column_name": "charterer",
                    "synonyms": [],
                }],
            }]

    context = await SemanticContextAssembler(
        LocalMetricCatalog(operator_published=False)
    ).assemble("astra", [], "Show fixture count by charterer")
    assert "unpublished_grouping_intent" not in context
    assert [metric["name"] for metric in context["metrics"]] == ["Fixture Count"]
