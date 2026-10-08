from datapilot.application.relationship_bootstrap import propose_relationships


def _catalog():
    return [
        {"schema_name": "s", "table_name": "orders", "columns": [{"name": "id"}, {"name": "customer_id"}]},
        {"schema_name": "s", "table_name": "customers", "columns": [{"name": "id"}]},
        {"schema_name": "s", "table_name": "unselected", "columns": [{"name": "id"}]},
    ]


def test_name_based_join_is_never_verified():
    selected = [{"schema_name": "s", "table_name": "orders"}, {"schema_name": "s", "table_name": "customers"}]
    results = propose_relationships(_catalog(), selected, [])
    assert len(results) == 1
    assert results[0].from_column == "customer_id"
    assert results[0].verified is False
    assert results[0].provenance == "column_name_heuristic"
    assert results[0].status == "draft"


def test_declared_foreign_key_is_verified_and_not_duplicated():
    selected = [{"schema_name": "s", "table_name": "orders"}, {"schema_name": "s", "table_name": "customers"}]
    fk = [{"schema_name": "s", "table_name": "orders", "from_column": "customer_id",
           "referenced_table": "customers", "to_column": "id"}]
    results = propose_relationships(_catalog(), selected, fk)
    assert len(results) == 1
    assert results[0].verified is True
    assert results[0].provenance == "declared_foreign_key"


def test_unselected_targets_are_excluded():
    results = propose_relationships(_catalog(), [{"schema_name": "s", "table_name": "orders"}], [])
    assert results == []


def test_cross_schema_unqualified_fk_not_guessed():
    catalog = [
        {"schema_name": "a", "table_name": "items", "columns": [{"name": "parent_id"}]},
        {"schema_name": "b", "table_name": "parents", "columns": [{"name": "id"}]},
    ]
    selected = [{"schema_name": t["schema_name"], "table_name": t["table_name"]} for t in catalog]
    fk = [{"schema_name": "a", "table_name": "items", "from_column": "parent_id",
           "referenced_table": "parents", "to_column": "id"}]
    assert propose_relationships(catalog, selected, fk) == []
