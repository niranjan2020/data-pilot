"""Provider-agnostic correctness repair regression tests.

Repairs must preserve the configured SQL dialect and must never broaden
an existing categorical predicate or silently bypass other failures.
"""
import pytest
from sqlglot import parse_one, exp

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.core.exceptions import SQLValidationError


ENTITIES = [{
    "name": "Assets",
    "attributes": [{
        "column_name": "ownership_status",
        "value_mappings": [
            {"canonical_value": "O", "synonyms": ["owned"]},
            {"canonical_value": "T", "synonyms": ["chartered"]},
        ],
    }],
}]


@pytest.mark.parametrize("dialect", ["postgresql", "postgres", "mysql", "duckdb"])
def test_categorical_repair_preserves_dialect_and_revalidates(dialect):
    sql = (
        "SELECT ownership_status, COUNT(*) FROM assets "
        "WHERE active = TRUE GROUP BY ownership_status"
    )
    with pytest.raises(SQLValidationError) as error:
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES
        )
    repaired = QueryOrchestrator._repair_explicit_categorical_comparison(
        sql, error.value, dialect=dialect,
    )
    assert repaired is not None
    ast = parse_one(repaired, read="postgres" if dialect == "postgresql" else dialect)
    assert isinstance(ast, exp.Select)
    assert len(list(ast.find_all(exp.Table))) == 1
    assert {str(x.this) for x in ast.find_all(exp.Literal) if x.is_string} >= {"O", "T"}
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Compare owned versus chartered assets", repaired, ENTITIES
    )


@pytest.mark.parametrize("dialect", ["postgresql", "postgres", "mysql", "duckdb"])
def test_categorical_repair_refuses_overwriting_one_sided_filter(dialect):
    sql = (
        "SELECT ownership_status, COUNT(*) FROM assets "
        "WHERE ownership_status = 'O' GROUP BY ownership_status"
    )
    with pytest.raises(SQLValidationError) as error:
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES
        )
    assert QueryOrchestrator._repair_explicit_categorical_comparison(
        sql, error.value, dialect=dialect,
    ) is None


@pytest.mark.parametrize("dialect", ["postgresql", "postgres", "mysql", "duckdb"])
def test_governed_filter_repair_respects_dialect(dialect):
    sql = "SELECT status, COUNT(*) FROM assets GROUP BY status"
    checks = [{
        "code": "filter_violation",
        "status": "failed",
        "column": "status",
        "operator": "=",
        "expected_value": "active",
    }]
    repaired = QueryOrchestrator._repair_missing_governed_filter(
        sql, checks, dialect=dialect,
    )
    assert repaired is not None
    ast = parse_one(repaired, read="postgres" if dialect == "postgresql" else dialect)
    assert isinstance(ast.args.get("where").this, exp.EQ)
    assert ast.args["where"].this.expression.this == "active"


@pytest.mark.parametrize("dialect", ["postgresql", "postgres", "mysql", "duckdb"])
def test_governed_filter_repair_rejects_conflicting_predicate(dialect):
    sql = "SELECT status, COUNT(*) FROM assets WHERE status = 'inactive' GROUP BY status"
    checks = [{
        "code": "filter_violation",
        "status": "failed",
        "column": "status",
        "operator": "=",
        "expected_value": "active",
    }]
    assert QueryOrchestrator._repair_missing_governed_filter(
        sql, checks, dialect=dialect,
    ) is None


@pytest.mark.parametrize("dialect", ["postgresql", "postgres", "mysql", "duckdb"])
def test_categorical_validator_uses_configured_dialect(dialect):
    sql = (
        "SELECT ownership_status, COUNT(*) FROM assets "
        "WHERE ownership_status IN ('O', 'T') GROUP BY ownership_status"
    )
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Compare owned versus chartered assets", sql, ENTITIES, dialect=dialect,
    )


@pytest.mark.parametrize("dialect", ["postgresql", "postgres", "mysql", "duckdb"])
def test_categorical_validator_rejects_missing_value_in_any_dialect(dialect):
    sql = (
        "SELECT ownership_status, COUNT(*) FROM assets "
        "WHERE ownership_status = 'O' GROUP BY ownership_status"
    )
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES, dialect=dialect,
        )
