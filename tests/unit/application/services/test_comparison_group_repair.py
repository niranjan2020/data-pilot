import pytest
from sqlglot import parse_one, exp
from datapilot.application.services.comparison_group_repair import repair_missing_comparison_groups

def checks(*names):
    return [{"code": "comparison_dimension_violation", "status": "failed",
             "missing_columns": list(names)}]

@pytest.mark.parametrize("table,cohort,measure", [
    ("astra.vessels", "operator", "id"),
    ("sales.orders", "customer", "id"),
    ("inventory.products", "supplier", "product_id"),
])
def test_repair_keeps_separate_cohorts(table, cohort, measure):
    sql = (f"SELECT segment, COUNT(DISTINCT {measure}) AS total FROM {table} "
           f"WHERE LOWER({cohort}) IN ('alpha', 'beta') GROUP BY segment LIMIT 1000")
    repaired = repair_missing_comparison_groups(sql, checks(cohort))
    assert repaired is not None
    ast = parse_one(repaired)
    grouped = {col.name for col in ast.args["group"].find_all(exp.Column)}
    selected = {col.name for item in ast.expressions for col in item.find_all(exp.Column)}
    assert cohort in grouped and cohort in selected
    assert "LIMIT 1000" in repaired.upper()
    assert len(list(ast.find_all(exp.Count))) == 1

@pytest.mark.parametrize("sql", [
    "SELECT segment, COUNT(*) FROM a JOIN b ON a.id=b.id WHERE a.operator IN ('x','y') GROUP BY segment",
    "SELECT DISTINCT segment, COUNT(*) FROM a WHERE operator IN ('x','y') GROUP BY segment",
    "SELECT segment, COUNT(*) FROM a WHERE operator IN ('x','y') GROUP BY segment HAVING COUNT(*) > 1",
    "SELECT segment, COUNT(*) FROM a WHERE operator='x' GROUP BY segment",
    "SELECT segment FROM a WHERE operator IN ('x','y')",
    "INVALID SQL ???",
])
def test_unsafe_shapes_are_not_repaired(sql):
    assert repair_missing_comparison_groups(sql, checks("operator")) is None

def test_other_failures_are_not_silenced():
    sql="SELECT segment, COUNT(*) FROM a WHERE operator IN ('x','y') GROUP BY segment"
    assert repair_missing_comparison_groups(sql, checks("operator")+[
        {"code":"metric_expression_violation","status":"failed"}
    ]) is None

def test_missing_unbound_column_fails_closed():
    sql="SELECT segment, COUNT(*) FROM a WHERE operator IN ('x','y') GROUP BY segment"
    assert repair_missing_comparison_groups(sql, checks("customer")) is None
