"""Offline observation of the existing NL-to-SQL workflow via its dry-run API.

The legacy orchestrator does not emit typed AnalyticalPlan objects. Therefore
these observations are NOT scored as successful golden predictions. The
database may still be accessed for schema/metadata; SQL execution is disabled.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datapilot.application.services.analytical_golden_questions import GoldenAnalyticalQuestion
from datapilot.domain.query import QueryRequest, QueryResponse


@dataclass(frozen=True)
class DryRunObservation:
    case_id: str
    status: str
    sql: str | None
    typed_plan_available: bool
    reason: str


async def observe_legacy_query_dry_run(
    *,
    case: GoldenAnalyticalQuestion,
    datasource: str,
    orchestrator: Any,
) -> DryRunObservation:
    """Run legacy generation without executing generated SQL or saving history.

    Must only be called by an authorized offline operator with a trusted
    orchestrator. The returned SQL is diagnostic, not verified golden evidence.
    """
    if not isinstance(case, GoldenAnalyticalQuestion):
        raise ValueError("A typed golden question is required")
    if not isinstance(datasource, str) or not datasource.strip():
        raise ValueError("Datasource is required")
    if orchestrator is None or not callable(getattr(orchestrator, "query", None)):
        raise ValueError("Query orchestrator is required")
    response = await orchestrator.query(QueryRequest(
        question=case.expectation.question,
        source_name=datasource,
        dry_run=True,
    ))
    if not isinstance(response, QueryResponse):
        raise ValueError("Unexpected query response")
    if response.question != case.expectation.question:
        raise ValueError("Query response question mismatch")
    if response.status == "completed":
        # A completed response is never accepted as offline evidence.
        raise ValueError("Offline observation unexpectedly completed execution")
    if response.result is not None:
        raise ValueError("Offline observation contains execution results")
    return DryRunObservation(
        case_id=case.expectation.case_id,
        status=response.status,
        sql=response.sql if response.status == "dry_run" else None,
        typed_plan_available=False,
        reason="legacy_query_has_no_typed_analytical_plan",
    )
