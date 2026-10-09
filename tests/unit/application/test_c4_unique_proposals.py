"""C4 semantic proposals must not auto-approve physical constraints."""

from datapilot.application.semantic_bootstrap import propose_datasets


def test_unique_constraints_are_evidence_not_publication():
    catalog = [{
        "schema_name": "astra",
        "table_name": "vessels",
        "columns": [{"name": "id", "is_primary_key": True}],
        "unique_constraints": [
            {"name": "vessels_pkey", "columns": ["id"], "is_primary_key": True}
        ],
    }]
    proposals = propose_datasets(catalog, [{"schema_name": "astra", "table_name": "vessels"}])
    assert proposals[0].status == "draft"
    assert proposals[0].unique_constraints[0]["columns"] == ["id"]
    assert "human approval" in proposals[0].warnings[0].lower()


def test_old_catalog_without_unique_evidence_still_proposes():
    catalog = [{
        "schema_name": "astra",
        "table_name": "fixtures",
        "columns": [{"name": "id", "is_primary_key": True}],
    }]
    proposal = propose_datasets(catalog, [{"schema_name": "astra", "table_name": "fixtures"}])[0]
    assert proposal.unique_constraints == []
