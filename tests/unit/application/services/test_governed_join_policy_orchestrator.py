"""Orchestrator boundary tests: governed joins must be checked before execution."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.core.exceptions import SQLValidationError
from datapilot.domain.policies import QueryExecutionPolicy


REL = {
    "name": "event_asset",
    "from_schema": "demo", "from_table": "demo.events", "from_column": "asset_id",
    "to_schema": "demo", "to_table": "demo.assets", "to_column": "id",
    "cardinality": "many_to_one", "join_policy": "preserve_source",
}
LEFT = "SELECT e.id FROM demo.events e LEFT JOIN demo.assets a ON e.asset_id = a.id"
INNER = "SELECT e.id FROM demo.events e INNER JOIN demo.assets a ON e.asset_id = a.id"
WRONG_KEY = "SELECT e.id FROM demo.events e LEFT JOIN demo.assets a ON e.id = a.id"


def orchestrator(sql):
    # Exercise the real validation/execution boundary without invoking an LLM or DB.
    service = object.__new__(QueryOrchestrator)
    service._database = SimpleNamespace(dialect="postgresql", execute=AsyncMock())
    service._validator = SimpleNamespace(validate=AsyncMock(return_value=SimpleNamespace(
        is_valid=True, sanitized_sql=sql, affected_tables=["demo.events", "demo.assets"],
        warnings=[], errors=[],
    )))
    service._query_policy = QueryExecutionPolicy()
    service._query_policy_enforcer = SimpleNamespace(enforce=Mock(return_value=SimpleNamespace(
        is_allowed=True, sql=sql, warnings=[], errors=[],
    )))
    return service


async def validate(service, sql, *, execute=False, relationship=None):
    return await service._validate_and_execute(
        question="Show events and assets", sql=sql, source="test",
        confidence=1.0, execute=execute,
        governed_tables=["demo.events", "demo.assets"],
        required_relationships=[relationship or REL],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("sql", [INNER, WRONG_KEY])
async def test_unsafe_join_rejected_before_policy_or_database(sql):
    service = orchestrator(sql)
    with pytest.raises(SQLValidationError) as exc:
        await validate(service, sql, execute=True)
    assert any(check["status"] == "failed" for check in exc.value.details["checks"])
    service._query_policy_enforcer.enforce.assert_not_called()
    service._database.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unconfigured_policy_rejected_before_execution():
    service = orchestrator(LEFT)
    with pytest.raises(SQLValidationError) as exc:
        await validate(service, LEFT, execute=True, relationship={**REL, "join_policy": "unconfigured"})
    assert any(check["code"] == "join_policy_violation" for check in exc.value.details["checks"])
    service._database.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_approved_join_reaches_policy_gate_in_dry_run():
    service = orchestrator(LEFT)
    response = await validate(service, LEFT, execute=False)
    assert response.status == "dry_run"
    service._query_policy_enforcer.enforce.assert_called_once()
    service._database.execute.assert_not_awaited()
