import pytest
from datapilot.application.services.named_text_filter import normalize_named_text_filter

@pytest.mark.parametrize("column,values", [
    ("operator", "('MSC', 'MAERSK')"),
    ("customer", "('ACME', 'Globex')"),
    ("brand", "('ALPHA', 'Beta')"),
])
def test_governed_text_in_normalized(column, values):
    sql = f"SELECT {column}, COUNT(*) FROM items WHERE {column} IN {values} GROUP BY {column}"
    result = normalize_named_text_filter(sql, attribute_column=column)
    assert f"LOWER({column}) IN" in result
    assert "'maersk'" in result if column == "operator" else "LOWER(" in result

@pytest.mark.parametrize("sql,column", [
    ("SELECT id FROM items WHERE ownership_status IN ('O', 'T')", "operator"),
    ("SELECT id FROM items WHERE operator = 'MAERSK'", "operator"),
    ("SELECT id FROM items WHERE operator IN ('MSC')", "operator"),
    ("SELECT id FROM items WHERE operator IN (1, 2)", "operator"),
    ("SELECT id FROM items", "operator"),
    ("SELECT id FROM a JOIN b ON a.id = b.id WHERE a.operator IN ('MSC','MAERSK')", "operator"),
])
def test_unsafe_or_unrelated_shapes_unchanged(sql, column):
    assert normalize_named_text_filter(sql, attribute_column=column) == sql

def test_requires_governed_column():
    with pytest.raises(ValueError):
        normalize_named_text_filter("SELECT 1", attribute_column="")


from datapilot.application.services.named_text_filter import normalize_governed_text_filters


@pytest.mark.parametrize("column,values", [
    ("operator", "('msc', 'maersk')"),
    ("customer", "('ACME', 'Globex')"),
    ("supplier", "('North', 'South')"),
])
def test_governed_text_filter_without_question_keyword(column, values):
    sql = f"SELECT {column}, COUNT(*) FROM items WHERE {column} IN {values} GROUP BY {column}"
    result = normalize_governed_text_filters(
        sql, governed_entities=[{"attributes": [{"name": column, "data_type": "text"}]}]
    )
    assert f"LOWER({column}) IN" in result
    assert "'maersk'" in result if column == "operator" else "LOWER(" in result


@pytest.mark.parametrize("attribute", [
    {"name": "ownership_status", "data_type": "text", "value_mappings": {"O": "Owned"}},
    {"name": "ownership_status", "data_type": "integer"},
    {"name": "ownership_status"},
    {"name": "ownership_status", "data_type": "text", "enum_values": ["O", "T"]},
])
def test_codes_nontext_and_untyped_are_not_rewritten(attribute):
    sql = "SELECT id FROM items WHERE ownership_status IN ('O', 'T')"
    assert normalize_governed_text_filters(
        sql, governed_entities=[{"attributes": [attribute]}]
    ) == sql


def test_only_governed_text_column_is_rewritten():
    sql = "SELECT id FROM items WHERE operator IN ('MSC','Maersk') AND ownership_status IN ('O','T')"
    result = normalize_governed_text_filters(sql, governed_entities=[{"attributes": [
        {"name": "operator", "data_type": "varchar"},
        {"name": "ownership_status", "data_type": "text", "value_mappings": {"O": "Owned"}},
    ]}])
    assert "LOWER(operator) IN" in result
    assert "ownership_status IN ('O', 'T')" in result


def test_conflicting_metadata_fails_closed_for_attribute():
    sql = "SELECT id FROM items WHERE operator IN ('MSC','Maersk')"
    result = normalize_governed_text_filters(sql, governed_entities=[
        {"attributes": [{"name": "operator", "data_type": "text"}]},
        {"attributes": [{"name": "operator", "data_type": "text", "value_mappings": {"MSC": "MSC"}}]},
    ])
    assert result == sql


from datapilot.domain.models import SchemaMetadata, TableMetadata, ColumnMetadata


def test_live_operator_filter_uses_physical_schema_when_semantic_type_absent():
    schema = SchemaMetadata(schema_name="astra", dialect="postgresql", tables=[
        TableMetadata(name="vessels", schema_name="astra", columns=[
            ColumnMetadata(name="operator", data_type="text"),
            ColumnMetadata(name="ownership_status", data_type="text"),
            ColumnMetadata(name="built_year", data_type="integer"),
        ])
    ])
    sql = (
        'SELECT "T1"."vessel_segment", COUNT(DISTINCT "T1"."id") FROM "astra"."vessels" AS "T1" '
        'WHERE "T1"."operator" IN (\'msc\', \'maersk\') AND "T1"."built_year" > 2020 '
        'GROUP BY "T1"."vessel_segment"'
    )
    result = normalize_governed_text_filters(sql, governed_entities=[
        {"attributes": [{"name": "operator"}, {"name": "ownership_status",
         "value_mappings": {"O": "Owned", "T": "Chartered"}}]}
    ], physical_schema=schema)
    assert 'LOWER("T1"."operator") IN (\'msc\', \'maersk\')' in result


def test_physical_schema_does_not_override_published_codes():
    schema = SchemaMetadata(schema_name="astra", dialect="postgresql", tables=[
        TableMetadata(name="vessels", schema_name="astra", columns=[
            ColumnMetadata(name="ownership_status", data_type="text"),
        ])
    ])
    sql = "SELECT id FROM astra.vessels WHERE ownership_status IN ('O', 'T')"
    result = normalize_governed_text_filters(sql, governed_entities=[
        {"attributes": [{"name": "ownership_status", "value_mappings": {"O": "Owned"}}]}
    ], physical_schema=schema)
    assert result == sql
