"""Canonical semantic mappings must become deterministic required filters."""
from datapilot.application.services.query_orchestrator import QueryOrchestrator


ENTITIES = [{
    "name": "Assets",
    "attributes": [{
        "name": "Ownership status",
        "column_name": "ownership_status",
        "semantic_type": "categorical",
        "value_mappings": [
            {"canonical_value": "O", "synonyms": ["owned"]},
            {"canonical_value": "T", "synonyms": ["time chartered"]},
            {"canonical_value": "TO", "synonyms": ["owned but chartered"]},
        ],
    }],
}]


def _filters(question):
    return QueryOrchestrator._required_filters(question, ENTITIES, [])


def test_published_synonym_resolves_to_canonical_filter():
    assert any(f["column_name"] == "ownership_status" and f["value"] == "O"
               for f in _filters("Show owned assets"))


def test_multiword_synonym_is_canonical():
    assert any(f["value"] == "TO" for f in _filters("Show owned but chartered assets"))


def test_range_connector_is_not_a_categorical_filter():
    assert not any(f["value"] == "TO" for f in _filters("Show assets built from 2015 to 2025"))


def test_quoted_category_code_is_explicit():
    assert any(f["value"] == "TO" for f in _filters("Show assets with status 'TO'"))


def test_multiple_values_do_not_generate_contradictory_equalities():
    assert not any(f["column_name"] == "ownership_status"
                   for f in _filters("Compare owned versus time chartered assets"))


def test_shared_value_phrase_across_attributes_is_not_assigned_arbitrarily():
    entities = [{"name": "Assets", "attributes": [
        {"column_name": "operator", "value_mappings": [{"canonical_value": "MSC"}]},
        {"column_name": "manager", "value_mappings": [{"canonical_value": "MSC"}]},
    ]}]
    assert QueryOrchestrator._required_filters("Show MSC assets", entities, []) == []


def test_published_array_category_does_not_become_scalar_equality():
    entities = [{"name": "Assets", "attributes": [{
        "column_name": "fuel_types", "data_type": "text[]",
        "value_mappings": [{"canonical_value": "LNG", "synonyms": ["liquefied natural gas"]}],
    }]}]
    filters = QueryOrchestrator._required_filters("Show LNG assets", entities, [])
    assert not any(f["column_name"] == "fuel_types" and f["operator"] == "=" for f in filters)


def test_published_scalar_category_still_generates_equality():
    assert any(f["column_name"] == "ownership_status" and f["value"] == "O"
               for f in _filters("Show owned assets"))
