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
