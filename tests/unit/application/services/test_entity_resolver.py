"""Tests for deterministic semantic entity/value resolution."""

from datapilot.application.services.entity_resolver import DeterministicEntityResolver
from datapilot.domain.models import SchemaMetadata
from datapilot.domain.semantic import EntityAttributeDefinition, EntityDefinition, SemanticCatalog


def _catalog() -> SemanticCatalog:
    return SemanticCatalog(
        entities=[
            EntityDefinition(
                name="customer",
                synonyms=["customers", "client", "clients"],
                table_name="customers",
                key_column="customer_id",
                display_column="customer_name",
                attributes=[
                    EntityAttributeDefinition(
                        name="country",
                        synonyms=["country", "region"],
                        column_name="country",
                    ),
                    EntityAttributeDefinition(
                        name="segment",
                        synonyms=["segment", "customer segment"],
                        column_name="segment",
                    ),
                ],
            ),
            EntityDefinition(
                name="order",
                synonyms=["orders", "purchases"],
                table_name="orders",
                key_column="order_id",
                display_column="customer_name",
            ),
        ]
    )


def test_resolves_entity_and_country_value() -> None:
    intent = DeterministicEntityResolver().resolve(
        "show customers in India",
        _catalog(),
        SchemaMetadata(),
    )

    assert intent.entity is not None
    assert intent.entity.name == "customer"
    assert intent.entity.table_name == "customers"
    assert len(intent.filters) == 1
    assert intent.filters[0].column_name == "country"
    assert intent.filters[0].value == "India"


def test_resolves_explicit_attribute_value() -> None:
    intent = DeterministicEntityResolver().resolve(
        "show customers where segment is enterprise",
        _catalog(),
        SchemaMetadata(),
    )

    assert intent.filters[0].attribute == "segment"
    assert intent.filters[0].column_name == "segment"
    assert intent.filters[0].value == "enterprise"


def test_resolves_entity_display_value_from_for_phrase() -> None:
    intent = DeterministicEntityResolver().resolve(
        "show orders for Acme",
        _catalog(),
        SchemaMetadata(),
    )

    assert intent.entity is not None
    assert intent.entity.name == "order"
    assert intent.filters[0].column_name == "customer_name"
    assert intent.filters[0].value == "Acme"


def test_ambiguous_entity_is_not_silently_selected() -> None:
    catalog = SemanticCatalog(
        entities=[
            EntityDefinition(
                name="customer",
                synonyms=["account"],
                table_name="customers",
                key_column="id",
            ),
            EntityDefinition(
                name="account",
                synonyms=["account"],
                table_name="accounts",
                key_column="id",
            ),
        ]
    )

    intent = DeterministicEntityResolver().resolve(
        "show account details",
        catalog,
        SchemaMetadata(),
    )

    assert intent.entity is None
    assert intent.ambiguities == ["account", "customer"]


def test_shared_exact_synonym_is_ambiguous_even_when_it_is_other_entity_name() -> None:
    catalog = SemanticCatalog(
        entities=[
            EntityDefinition(
                name="customer",
                synonyms=["account"],
                table_name="customers",
                key_column="id",
            ),
            EntityDefinition(
                name="account",
                synonyms=[],
                table_name="accounts",
                key_column="id",
            ),
        ]
    )

    intent = DeterministicEntityResolver().resolve(
        "show account details",
        catalog,
        SchemaMetadata(),
    )

    assert intent.entity is None
    assert intent.ambiguities == ["account", "customer"]


def test_distinct_exact_entity_terms_are_not_made_ambiguous() -> None:
    intent = DeterministicEntityResolver().resolve(
        "show customer details",
        _catalog(),
        SchemaMetadata(),
    )

    assert intent.entity is not None
    assert intent.entity.name == "customer"
    assert intent.ambiguities == []


def test_many_synonyms_do_not_dilute_exact_entity_match() -> None:
    catalog = SemanticCatalog(
        entities=[
            EntityDefinition(
                name="customer",
                synonyms=["buyer", "client", "account", "purchaser", "subscriber"],
                table_name="customers",
                key_column="id",
            ),
        ]
    )

    intent = DeterministicEntityResolver().resolve(
        "list customer details",
        catalog,
        SchemaMetadata(),
    )

    assert intent.entity is not None
    assert intent.entity.name == "customer"
    assert intent.entity.confidence == 1.0


def test_exact_synonym_is_scored_as_alternative_entity_name() -> None:
    catalog = SemanticCatalog(
        entities=[
            EntityDefinition(
                name="customer",
                synonyms=["buyer", "client", "account", "purchaser", "subscriber"],
                table_name="customers",
                key_column="id",
            ),
        ]
    )

    intent = DeterministicEntityResolver().resolve(
        "show purchaser details",
        catalog,
        SchemaMetadata(),
    )

    assert intent.entity is not None
    assert intent.entity.name == "customer"
    assert intent.entity.confidence == 1.0
