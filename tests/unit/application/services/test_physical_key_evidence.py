"""Adversarial tests for physical uniqueness metadata verification."""

import pytest

from datapilot.application.services.physical_key_evidence import assess_declared_unique_key


BASE = {
    "name": "parents_children",
    "to_schema": "demo",
    "to_table": "children",
    "to_column": "parent_id",
    "to_unique_columns": ["parent_id"],
    "to_unique_key_verified": True,
}


@pytest.mark.parametrize("side", ["from", "to"])
def test_unique_key_side_must_be_explicit(side):
    metadata = dict(BASE)
    if side == "from":
        metadata.update({
            "from_schema": "demo",
            "from_table": "parents",
            "from_column": "id",
            "from_unique_columns": ["id"],
            "from_unique_key_verified": True,
        })
    result = assess_declared_unique_key(metadata, side=side)
    assert result["code"] == "fanout_physical_unique_key_verified"
    assert result["join_cardinality_safe"] is False


@pytest.mark.parametrize("field,value", [
    ("to_schema", None),
    ("to_schema", ""),
    ("to_table", None),
    ("to_table", ""),
    ("to_column", None),
    ("to_column", ""),
    ("to_unique_columns", None),
    ("to_unique_columns", []),
    ("to_unique_columns", ["id"]),
    ("to_unique_columns", ["parent_id", "id"]),
    ("to_unique_columns", "parent_id"),
    ("to_unique_columns", [123]),
    ("to_unique_columns", ["parent_id", "parent_id"]),
    ("to_unique_key_verified", False),
    ("to_unique_key_verified", None),
    ("to_unique_key_verified", 1),
    ("to_unique_key_verified", "true"),
    ("to_unique_key_verified", "yes"),
])
def test_untrusted_or_incomplete_unique_key_declaration_rejected(field, value):
    metadata = {**BASE, field: value}
    result = assess_declared_unique_key(metadata)
    assert result["code"] == "fanout_physical_unique_key_unverified"
    assert result["unique_key_verified"] is False


@pytest.mark.parametrize("key", [
    "to_schema", "to_table", "to_column",
    "to_unique_columns", "to_unique_key_verified",
])
def test_missing_unique_key_metadata_rejected(key):
    metadata = dict(BASE)
    del metadata[key]
    assert assess_declared_unique_key(metadata)["status"] == "skipped"


def test_unique_key_diagnostic_never_approves_fanout():
    result = assess_declared_unique_key(BASE)
    assert result["unique_key_verified"] is True
    assert result["join_cardinality_safe"] is False


def test_invalid_side_is_rejected():
    with pytest.raises(ValueError):
        assess_declared_unique_key(BASE, side="both")
