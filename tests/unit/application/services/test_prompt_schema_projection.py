"""Governed metric prompts must not expose unrelated physical columns."""
from datapilot.application.services.prompt_schema_projection import project_metric_prompt_schema
from datapilot.domain.models import SchemaMetadata, TableMetadata, ColumnMetadata


def _schema():
    def col(name):
        return ColumnMetadata(name=name, data_type="text")
    return SchemaMetadata(tables=[
        TableMetadata(schema_name="astra", name="fixtures",
                      columns=[col("id"), col("vessel_id"), col("operator_next")]),
        TableMetadata(schema_name="astra", name="vessels",
                      columns=[col("id"), col("operator"), col("ownership_status")]),
    ])


def _context():
    return {
        "metrics": [{"entity_id": 25, "attribute_name": "Id"}],
        "entities": [
            {"id": 25, "schema_name": "astra", "table_name": "fixtures",
             "key_column": "id", "attributes": [{"name": "Id", "column_name": "id"}]},
            {"id": 12, "schema_name": "astra", "table_name": "vessels",
             "key_column": "id", "attributes": []},
        ],
        "published_dimensions": [
            {"entity_id": 12, "column_name": "operator", "name": "Operator"}
        ],
        "relationships": [
            {"from_entity_id": 25, "to_entity_id": 12,
             "from_column": "vessel_id", "to_column": "id"}
        ],
    }


def test_metric_prompt_contains_only_published_dimension_metric_and_join_keys():
    original = _schema()
    projected = project_metric_prompt_schema(
        original, _context(), authoritative_dimensions=True,
    )
    assert [(t.name, [c.name for c in t.columns]) for t in projected.tables] == [
        ("fixtures", ["id", "vessel_id"]),
        ("vessels", ["id", "operator"]),
    ]
    assert any(c.name == "operator_next" for c in original.tables[0].columns)


def test_unpublished_operator_is_not_implicitly_available():
    context = _context()
    context["published_dimensions"] = []
    projected = project_metric_prompt_schema(
        _schema(), context, authoritative_dimensions=True,
    )
    assert all(c.name != "operator" for t in projected.tables for c in t.columns)
    assert all(c.name != "operator_next" for t in projected.tables for c in t.columns)


def test_legacy_schema_without_authoritative_publications_is_unchanged():
    schema = _schema()
    assert project_metric_prompt_schema(
        schema, _context(), authoritative_dimensions=False,
    ) is schema


def test_non_metric_question_preserves_schema_discovery():
    schema = _schema()
    context = _context()
    context["metrics"] = []
    assert project_metric_prompt_schema(
        schema, context, authoritative_dimensions=True,
    ) is schema


def test_single_entity_metric_keeps_configured_grouping_attributes():
    schema = _schema()
    context = {
        "metrics": [{"entity_id": 12, "attribute_name": "Id"}],
        "entities": [{
            "id": 12, "schema_name": "astra", "table_name": "vessels",
            "key_column": "id",
            "attributes": [
                {"name": "Managing Owner", "column_name": "ownership_status"},
                {"name": "Operator", "column_name": "operator"},
            ],
        }],
        "published_dimensions": [],
        "relationships": [],
    }
    projected = project_metric_prompt_schema(
        schema, context, authoritative_dimensions=True,
    )
    assert [(table.name, [col.name for col in table.columns])
            for table in projected.tables] == [
        ("vessels", ["id", "operator", "ownership_status"])
    ]


def test_other_entity_near_name_remains_excluded_from_metric_prompt():
    context = _context()
    context["published_dimensions"] = []
    context["entities"][0]["attributes"] = [
        {"name": "Id", "column_name": "id"},
    ]
    projected = project_metric_prompt_schema(
        _schema(), context, authoritative_dimensions=True,
    )
    assert all(
        column.name != "operator_next"
        for table in projected.tables for column in table.columns
    )
