"""Tests for the versioned semantic evaluation fixture."""

import json
from pathlib import Path

from datapilot.domain.semantic import SemanticCatalog


FIXTURE = Path(__file__).parents[1] / "fixtures" / "semantic" / "catalog.json"


def load_semantic_fixture() -> SemanticCatalog:
    return SemanticCatalog.model_validate(
        json.loads(FIXTURE.read_text(encoding="utf-8"))
    )


def test_semantic_fixture_validates_with_production_domain_model():
    catalog = load_semantic_fixture()

    assert {entity.name for entity in catalog.entities} == {
        "Customer", "Product", "Order"
    }
    assert {metric.name for metric in catalog.metrics} == {
        "Revenue", "Units Sold", "Order Count"
    }


def test_semantic_fixture_contains_controlled_entity_ambiguity():
    catalog = load_semantic_fixture()

    account_entities = {
        entity.name
        for entity in catalog.entities
        if "account" in {synonym.casefold() for synonym in entity.synonyms}
    }

    assert account_entities == {"Customer", "Order"}
