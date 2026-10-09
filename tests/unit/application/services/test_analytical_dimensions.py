import pytest

from datapilot.application.services.analytical_dimensions import (
    extract_analytical_dimensions, resolve_analytical_dimension,
)


def entity(identifier=1, name="Customer", attributes=None):
    return {
        "id": identifier, "name": name, "schema_name": "Sales",
        "table_name": name, "attributes": attributes if attributes is not None else [
            {"name": "Region", "column_name": "RegionCode"},
        ],
    }


def test_entity_is_not_automatically_a_dimension():
    dimensions = extract_analytical_dimensions([entity()])
    assert [d.name for d in dimensions] == ["Region"]
    assert dimensions[0].column_name == "RegionCode"


def test_dimension_preserves_owner_and_physical_mapping():
    dimension = extract_analytical_dimensions([entity()])[0]
    assert (dimension.entity_id, dimension.entity_name) == (1, "Customer")
    assert (dimension.schema_name, dimension.table_name) == ("Sales", "Customer")


def test_unambiguous_dimension_resolves_by_attribute_name():
    dimensions = extract_analytical_dimensions([entity()])
    assert resolve_analytical_dimension(dimensions, "region").entity_id == 1


def test_qualified_dimension_resolves_when_names_overlap():
    dimensions = extract_analytical_dimensions([
        entity(), entity(2, "Supplier"),
    ])
    assert resolve_analytical_dimension(dimensions, "Supplier.Region").entity_id == 2


def test_unqualified_duplicate_dimension_is_ambiguous():
    dimensions = extract_analytical_dimensions([
        entity(), entity(2, "Supplier"),
    ])
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_analytical_dimension(dimensions, "Region")


def test_missing_attribute_mapping_is_rejected():
    with pytest.raises(ValueError, match="Incomplete governed attribute"):
        extract_analytical_dimensions([
            entity(attributes=[{"name": "Region"}]),
        ])


def test_duplicate_attribute_is_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        extract_analytical_dimensions([
            entity(attributes=[
                {"name": "Region", "column_name": "A"},
                {"name": "region", "column_name": "B"},
            ]),
        ])


def test_entity_without_attributes_produces_no_dimensions():
    assert extract_analytical_dimensions([
        entity(attributes=[]),
    ]) == ()


def test_unknown_dimension_is_rejected():
    with pytest.raises(ValueError, match="Unknown"):
        resolve_analytical_dimension(
            extract_analytical_dimensions([entity()]), "Customer",
        )


def test_invalid_entity_identifier_is_rejected():
    with pytest.raises(ValueError, match="identifier"):
        extract_analytical_dimensions([entity(identifier=True)])
