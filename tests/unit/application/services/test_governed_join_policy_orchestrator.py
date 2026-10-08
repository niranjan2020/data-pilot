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
        question="Show events and assets", sql=sql, source="generator",
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


# Exercise the configured production publication boundary, not just legacy policy.
PUBLISHED = {
    **REL,
    "review_status": "approved",
}


def governed_service(sql, publications, *, source_id=7):
    service = orchestrator(sql)
    metadata = SimpleNamespace(
        get_data_source_id=AsyncMock(return_value=source_id),
        list_current_relationship_publications=AsyncMock(return_value=publications),
    )
    service._relationship_publication_metadata = metadata
    return service, metadata


async def governed_validate(service, sql, relationships, *, source="sample", execute=False):
    return await service._validate_and_execute(
        question="Show events and assets", sql=sql, source="generator",
        confidence=1.0, execute=execute, data_source_name=source,
        governed_tables=["demo.events", "demo.assets"],
        required_relationships=relationships,
    )


@pytest.mark.asyncio
async def test_published_join_dry_run_uses_one_catalog_snapshot():
    service, metadata = governed_service(LEFT, [PUBLISHED])
    response = await governed_validate(service, LEFT, [PUBLISHED])
    assert response.status == "dry_run"
    metadata.get_data_source_id.assert_awaited_once_with("sample")
    metadata.list_current_relationship_publications.assert_awaited_once_with(7)
    service._database.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("publications", [[], [{**PUBLISHED, "from_column": "wrong"}]])
async def test_unpublished_or_mismatched_join_denied_before_execution(publications):
    service, metadata = governed_service(LEFT, publications)
    with pytest.raises(SQLValidationError) as exc:
        await governed_validate(service, LEFT, [PUBLISHED], execute=True)
    assert exc.value.details["checks"][0]["code"] == "relationship_publication_violation"
    service._database.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_join_without_required_contract_is_denied():
    service, metadata = governed_service(LEFT, [PUBLISHED])
    with pytest.raises(SQLValidationError) as exc:
        await governed_validate(service, LEFT, [], execute=True)
    assert exc.value.details["checks"][0]["code"] == "relationship_publication_violation"
    metadata.list_current_relationship_publications.assert_not_awaited()
    service._database.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_datasource_identity_fails_closed():
    service, metadata = governed_service(LEFT, [PUBLISHED])
    with pytest.raises(SQLValidationError):
        await governed_validate(service, LEFT, [PUBLISHED], source=None, execute=True)
    metadata.get_data_source_id.assert_not_awaited()
    metadata.list_current_relationship_publications.assert_not_awaited()
    service._database.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_join_type_denied_even_when_relationship_published():
    service, metadata = governed_service(INNER, [PUBLISHED])
    with pytest.raises(SQLValidationError):
        await governed_validate(service, INNER, [PUBLISHED], execute=True)
    service._database.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_published_join_with_wrong_key_fails_before_execution():
    service, metadata = governed_service(WRONG_KEY, [PUBLISHED])
    with pytest.raises(SQLValidationError):
        await governed_validate(service, WRONG_KEY, [PUBLISHED], execute=True)
    metadata.list_current_relationship_publications.assert_awaited_once()
    service._database.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_datasource_fails_without_publication_lookup():
    service, metadata = governed_service(LEFT, [PUBLISHED], source_id=None)
    with pytest.raises(SQLValidationError):
        await governed_validate(service, LEFT, [PUBLISHED], execute=True)
    metadata.get_data_source_id.assert_awaited_once_with("sample")
    metadata.list_current_relationship_publications.assert_not_awaited()
    service._database.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_join_inside_nested_select_without_contract_fails_closed():
    sql = "SELECT * FROM (SELECT e.id FROM demo.events e LEFT JOIN demo.assets a ON e.asset_id = a.id) q"
    service, metadata = governed_service(sql, [PUBLISHED])
    with pytest.raises(SQLValidationError):
        await governed_validate(service, sql, [], execute=True)
    metadata.list_current_relationship_publications.assert_not_awaited()
    service._database.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_join_query_does_not_need_publication_lookup():
    sql = "SELECT e.id FROM demo.events e"
    service, metadata = governed_service(sql, [PUBLISHED])
    service._validator.validate.return_value.affected_tables = ["demo.events"]
    response = await service._validate_and_execute(
        question="Show events", sql=sql, source="generator",
        confidence=1.0, execute=False, data_source_name="sample",
        governed_tables=["demo.events"], required_relationships=[],
    )
    assert response.status == "dry_run"
    metadata.get_data_source_id.assert_not_awaited()
    metadata.list_current_relationship_publications.assert_not_awaited()


# Three Astra regression scenarios reported during first-run onboarding.
@pytest.mark.asyncio
@pytest.mark.parametrize("question,sql", [
    ("How many vessels are there?",
     'SELECT COUNT(DISTINCT "id") FROM "astra"."vessels"'),
    ("How many on order and delivered vessels does MSC have?",
     "SELECT vessel_status, COUNT(DISTINCT id) FROM astra.vessels "
     "WHERE operator = 'MSC' GROUP BY vessel_status"),
])
async def test_onboarded_vessel_aggregates_accept_valid_qualifiers(question, sql):
    service = orchestrator(sql)
    service._onboarding_allowed_tables = frozenset({"astra.vessels"})
    service._validator.validate.return_value.affected_tables = ["astra.vessels"]
    response = await service._validate_and_execute(
        question=question, sql=sql, source="generator",
        confidence=1.0, execute=False, governed_tables=["astra.vessels"],
    )
    assert response.status == "dry_run"


@pytest.mark.asyncio
@pytest.mark.parametrize("sql", [
    'SELECT COUNT(DISTINCT astra."id") FROM "astra"."vessels"',
    'SELECT COUNT(DISTINCT astra."id") FROM "astra"."vessels" WHERE astra."operator" = \'MSC\'',
])
async def test_single_table_schema_column_qualifier_is_repaired(sql):
    service = orchestrator(sql)
    service._onboarding_allowed_tables = frozenset({"astra.vessels"})
    service._validator.validate.return_value.affected_tables = ["astra.vessels"]
    response = await service._validate_and_execute(
        question="How many vessels does MSC have?", sql=sql,
        source="generator", confidence=1.0, execute=False,
        governed_tables=["astra.vessels"],
    )
    assert response.status == "dry_run"
    assert service._validator.validate.await_count == 2
    repaired = service._validator.validate.await_args_list[-1].args[0]
    assert 'astra."id"' not in repaired
    assert 'astra."operator"' not in repaired
    assert '"vessels"."id"' in repaired


@pytest.mark.asyncio
async def test_ambiguous_schema_qualifier_is_not_repaired():
    sql = 'SELECT COUNT(DISTINCT astra."id") FROM astra.vessels v JOIN astra.fixtures f ON v.id = f.vessel_id'
    service = orchestrator(sql)
    service._onboarding_allowed_tables = frozenset({"astra.vessels", "astra.fixtures"})
    service._validator.validate.return_value.affected_tables = ["astra.vessels", "astra.fixtures"]
    with pytest.raises(SQLValidationError) as exc:
        await service._validate_and_execute(
            question="Count joined vessels", sql=sql, source="generator",
            confidence=1.0, execute=True, governed_tables=["astra.vessels", "astra.fixtures"],
        )
    assert exc.value.details["checks"][0]["code"] == "sql_identifier_qualifier_violation"
    service._database.execute.assert_not_awaited()
