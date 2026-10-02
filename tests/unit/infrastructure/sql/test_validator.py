"""Unit tests for the SQL AST safety validator."""

import pytest

from datapilot.infrastructure.sql import SQLGlotValidator


@pytest.fixture
def validator() -> SQLGlotValidator:
    return SQLGlotValidator()


@pytest.mark.asyncio
async def test_select_is_valid_and_extracts_tables(validator: SQLGlotValidator) -> None:
    result = await validator.validate(
        "SELECT operator, COUNT(*) AS vessel_count FROM vessels GROUP BY operator LIMIT 10"
    )

    assert result.is_valid is True
    assert result.is_read_only is True
    assert result.errors == []
    assert result.affected_tables == ["vessels"]
    assert result.sanitized_sql is not None


@pytest.mark.asyncio
async def test_select_without_limit_is_valid_with_warning(validator: SQLGlotValidator) -> None:
    result = await validator.validate("SELECT * FROM vessels")

    assert result.is_valid is True
    assert result.is_read_only is True
    assert "LIMIT" in result.warnings[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO vessels (imo) VALUES (123)",
        "UPDATE vessels SET vessel_name = 'x'",
        "DELETE FROM vessels",
        "DROP TABLE vessels",
        "ALTER TABLE vessels ADD COLUMN x TEXT",
        "TRUNCATE TABLE vessels",
    ],
)
async def test_mutating_statements_are_rejected(
    validator: SQLGlotValidator, sql: str
) -> None:
    result = await validator.validate(sql)

    assert result.is_valid is False
    assert result.is_read_only is False


@pytest.mark.asyncio
async def test_multiple_statements_are_rejected(validator: SQLGlotValidator) -> None:
    result = await validator.validate("SELECT * FROM vessels; DELETE FROM vessels")

    assert result.is_valid is False
    assert result.is_read_only is False
    assert "Multiple SQL statements" in result.errors[0]


@pytest.mark.asyncio
async def test_invalid_sql_is_rejected(validator: SQLGlotValidator) -> None:
    result = await validator.validate("SELEC * FROM vessels")

    assert result.is_valid is False
    assert result.is_read_only is False
    assert result.errors


@pytest.mark.asyncio
async def test_data_modifying_cte_is_rejected(validator: SQLGlotValidator) -> None:
    result = await validator.validate(
        "WITH changed AS (DELETE FROM vessels RETURNING imo) SELECT * FROM changed"
    )

    assert result.is_valid is False
    assert result.is_read_only is False


@pytest.mark.asyncio
async def test_dialect_is_passed_to_parser(validator: SQLGlotValidator) -> None:
    result = await validator.validate(
        "SELECT TOP 10 * FROM vessels",
        dialect="tsql",
    )

    assert result.is_valid is True
    assert result.is_read_only is True
