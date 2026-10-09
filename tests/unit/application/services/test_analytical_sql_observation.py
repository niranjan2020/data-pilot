"""Conservative cross-domain SQL AST observation checks."""
import pytest

from datapilot.application.services.analytical_legacy_observation import DryRunObservation
from datapilot.application.services.analytical_sql_observation import inspect_analytical_sql_observation
from datapilot.application.services.analytical_plan import AnalyticalOperation as Op


def inspect(sql, status="dry_run", dialect="postgres"):
    return inspect_analytical_sql_observation(
        DryRunObservation("gold", status, sql, False, "legacy"), dialect=dialect,
    )


@pytest.mark.parametrize("sql,operations,source", [
    ('SELECT "category", SUM("amount") FROM "sales"."orders" GROUP BY "category" ORDER BY SUM("amount") DESC LIMIT 5',
     (Op.GROUP, Op.AGGREGATE, Op.SORT, Op.LIMIT), "sales.orders"),
    ('SELECT "owner", COUNT("id") FROM "fleet"."vessels" WHERE "status" = \'O\' GROUP BY "owner" ORDER BY COUNT("id") DESC LIMIT 10',
     (Op.FILTER, Op.GROUP, Op.AGGREGATE, Op.SORT, Op.LIMIT), "fleet.vessels"),
    ('SELECT category, COUNT(id) FROM items GROUP BY category', (Op.GROUP, Op.AGGREGATE), "items"),
    ('SELECT id FROM items WHERE color = \'red\' LIMIT 20', (Op.FILTER, Op.LIMIT), "items"),
    ('SELECT id FROM items ORDER BY id', (Op.SORT,), "items"),
    ('SELECT id FROM items', (), "items"),
    ('SELECT SUM(price) FROM items', (Op.AGGREGATE,), "items"),
    ('SELECT id FROM items WHERE id > 5', (Op.FILTER,), "items"),
])
def test_simple_sql_operations(sql, operations, source):
    result = inspect(sql)
    assert result.supported is True
    assert result.operations == operations
    assert result.sources == (source,)
    assert result.semantic_verified is False
    assert result.reasons == ("semantic_binding_not_verified",)


@pytest.mark.parametrize("sql,reason", [
    ("SELECT * FROM items", "wildcard_projection"),
    ("SELECT a.id FROM a JOIN b ON a.id = b.id", "complex_sql_not_supported"),
    ("SELECT id FROM items UNION SELECT id FROM other", "unsupported_statement"),
    ("WITH x AS (SELECT id FROM items) SELECT id FROM x", "complex_sql_not_supported"),
    ("SELECT id FROM items WHERE id IN (SELECT id FROM other)", "complex_sql_not_supported"),
    ("SELECT category, COUNT(id) FROM items GROUP BY category HAVING COUNT(id) > 2", "complex_sql_not_supported"),
    ("SELECT id FROM items OFFSET 2", "unsupported_sql_modifier"),
    ("SELECT DISTINCT id FROM items", "unsupported_sql_modifier"),
    ("SELECT 1", "source_not_unique"),
    ("DELETE FROM items", "unsupported_statement"),
    ("SELECT id FROM items; SELECT id FROM items", "unsupported_statement"),
    ("not sql syntax ###", "sql_parse_failed"),
])
def test_unsupported_sql_never_claims_support(sql, reason):
    result = inspect(sql)
    assert result.supported is False
    assert result.semantic_verified is False
    assert result.reasons == (reason,)


@pytest.mark.parametrize("status", ["ambiguous", "rejected", "completed"])
def test_non_dry_run_has_no_sql_evidence(status):
    result = inspect("SELECT id FROM items", status=status)
    assert result.supported is False
    assert result.reasons == ("sql_not_available",)


def test_missing_sql_has_no_evidence():
    assert inspect(None).reasons == ("sql_not_available",)


def test_invalid_observation_rejected():
    with pytest.raises(ValueError, match="observation"):
        inspect_analytical_sql_observation(None)


def test_invalid_dialect_rejected():
    with pytest.raises(ValueError, match="dialect"):
        inspect("SELECT id FROM items", dialect="")


def test_typed_plan_observation_not_accepted():
    with pytest.raises(ValueError, match="typed-plan"):
        inspect_analytical_sql_observation(
            DryRunObservation("gold", "dry_run", "SELECT id FROM items", True, "typed"),
        )
