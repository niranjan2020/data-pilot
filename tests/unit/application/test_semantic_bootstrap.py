from datapilot.application.semantic_bootstrap import propose_datasets
import pytest


def test_bootstrap_only_uses_approved_physical_datasets():
    catalog = [
        {"schema_name": "alpha", "table_name": "orders", "columns": [
            {"name": "id", "is_primary_key": True},
            {"name": "amount", "is_primary_key": False},
        ]},
        {"schema_name": "alpha", "table_name": "private", "columns": []},
    ]
    result = propose_datasets(catalog, [{"schema_name": "alpha", "table_name": "orders"}])
    assert len(result) == 1
    assert result[0].key_columns == ["id"]
    assert result[0].attributes == ["id", "amount"]
    assert result[0].status == "draft"
    assert result[0].provenance == "discovered_schema"
    assert not hasattr(result[0], "metrics")


def test_bootstrap_rejects_unapproved_unknown_catalog_entries():
    with pytest.raises(ValueError):
        propose_datasets([], [{"schema_name": "unknown", "table_name": "missing"}])


def test_bootstrap_flags_missing_primary_key_without_inventing_grain():
    result = propose_datasets(
        [{"schema_name": "s", "table_name": "v", "columns": [{"name": "x", "is_primary_key": False}]}],
        [{"schema_name": "s", "table_name": "v"}],
    )
    assert result[0].key_columns == []
    assert any("identity is unknown" in w for w in result[0].warnings)
