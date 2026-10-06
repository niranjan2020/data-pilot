"""Deterministic query explainability derived from authoritative response evidence."""

from __future__ import annotations

from typing import Any

from datapilot.domain.query import (
    QueryExplanation,
    QueryExplanationStep,
    QueryResponse,
    QueryTrace,
)


def build_query_explanation(response: QueryResponse) -> QueryExplanation:
    """Build a compact explanation without model reasoning or orchestration side effects."""
    trace = response.trace or QueryTrace()
    steps: list[QueryExplanationStep] = []

    selected_candidates = [
        {
            "kind": item.get("kind"),
            "name": item.get("name"),
            "score": item.get("score"),
        }
        for item in trace.retrieved_candidates
        if item.get("decision") == "selected"
    ]
    if trace.retrieved_candidates:
        steps.append(QueryExplanationStep(
            stage="retrieval",
            status="selected",
            summary=(
                f"Semantic retrieval considered {len(trace.retrieved_candidates)} candidates; "
                f"{len(selected_candidates)} were admitted to governed context."
            ),
            evidence={"selected_candidates": selected_candidates},
        ))

    governed = {
        "datasets": list(trace.governed_datasets),
        "entities": list(trace.governed_entities),
        "relationships": list(trace.governed_relationships),
        "metrics": list(trace.governed_metrics),
        "business_rules": list(trace.governed_business_rules),
        "time_dimensions": list(trace.governed_time_dimensions),
    }
    if any(governed.values()):
        steps.append(QueryExplanationStep(
            stage="governance",
            status="selected",
            summary="Governed semantic metadata constrained the interpretation and executable scope.",
            evidence={key: value for key, value in governed.items() if value},
        ))

    if response.status == "ambiguous":
        clarification = response.clarification
        evidence: dict[str, Any] = {}
        if clarification is not None:
            evidence = {
                "kind": clarification.kind,
                "key": clarification.key,
                "options": [option.value for option in clarification.options],
            }
        steps.append(QueryExplanationStep(
            stage="clarification",
            status="clarification_required",
            summary=response.message or "A governed clarification is required before SQL generation.",
            evidence=evidence,
        ))

    if trace.time_interpretation:
        steps.append(QueryExplanationStep(
            stage="time",
            status=(
                "clarification_required"
                if trace.time_interpretation.get("status") == "ambiguous"
                else "applied"
            ),
            summary="Deterministic governed time semantics were applied.",
            evidence=dict(trace.time_interpretation),
        ))

    sql_lineage = _sql_lineage(trace)
    if trace.generated_sql:
        steps.append(QueryExplanationStep(
            stage="generation",
            status="applied",
            summary="A candidate SQL statement was generated from the governed query context.",
        ))
    if trace.bound_sql and trace.bound_sql != trace.generated_sql:
        steps.append(QueryExplanationStep(
            stage="binding",
            status="applied",
            summary="Physical identifiers were bound using the configured database dialect boundary.",
        ))
    if trace.validated_sql:
        steps.append(QueryExplanationStep(
            stage="validation",
            status="passed",
            summary="SQL passed deterministic read-only and AST safety validation.",
            evidence={
                "affected_tables": list(trace.validation_affected_tables),
                "warnings": list(trace.validation_warnings),
            },
        ))

    if trace.correctness_checks:
        failed = [check for check in trace.correctness_checks if check.get("status") == "failed"]
        unavailable = [
            check for check in trace.correctness_checks
            if check.get("status") == "skipped"
            and str(check.get("code") or "").endswith("_verification_unavailable")
        ]
        steps.append(QueryExplanationStep(
            stage="correctness",
            status="passed" if not failed and not unavailable else "rejected",
            summary=(
                "Deterministic governed correctness checks passed."
                if not failed and not unavailable
                else "Deterministic governed correctness checks blocked this SQL proposal."
            ),
            evidence={
                "checks": list(trace.correctness_checks),
            },
        ))

    if trace.correction_attempts:
        steps.append(QueryExplanationStep(
            stage="correction",
            status="corrected",
            summary="One bounded governed-correctness SQL correction was attempted.",
            evidence={"attempt_count": len(trace.correction_attempts)},
        ))

    if trace.execution_recovery_attempts:
        steps.append(QueryExplanationStep(
            stage="recovery",
            status="recovered",
            summary="One bounded recoverable database execution correction was attempted.",
            evidence={"attempt_count": len(trace.execution_recovery_attempts)},
        ))

    if trace.policy_sql:
        steps.append(QueryExplanationStep(
            stage="policy",
            status="passed",
            summary="SQL passed the deterministic execution resource policy.",
            evidence={
                "warnings": list(trace.policy_warnings),
                "resource_budget": dict(trace.resource_budget),
            },
        ))

    if trace.execution:
        executed = trace.execution.get("executed") is not False
        steps.append(QueryExplanationStep(
            stage="execution",
            status="executed" if executed else "not_executed",
            summary=(
                "The policy-approved SQL was executed."
                if executed
                else "Execution was intentionally skipped for this dry run."
            ),
            evidence=dict(trace.execution),
        ))

    if response.status == "rejected":
        rejection_evidence: dict[str, Any] = {}
        if response.rejection is not None:
            rejection_evidence = {
                "code": response.rejection.code,
                "category": response.rejection.category,
                "reason": response.rejection.reason,
            }
        steps.append(QueryExplanationStep(
            stage="outcome",
            status="rejected",
            summary=response.message or "The question was rejected before execution.",
            evidence=rejection_evidence,
        ))

    return QueryExplanation(
        outcome=response.status,
        summary=_outcome_summary(response),
        steps=steps,
        sql_lineage=sql_lineage,
        governed_interpretation=governed,
        resource_policy=dict(trace.resource_budget),
    )


def _sql_lineage(trace: QueryTrace) -> list[dict[str, str]]:
    lineage: list[dict[str, str]] = []
    values = (
        ("generated", trace.generated_sql),
        ("bound", trace.bound_sql),
        ("validated", trace.validated_sql),
        ("policy", trace.policy_sql),
    )
    previous: str | None = None
    for stage, sql in values:
        if not sql:
            continue
        if sql == previous:
            previous = sql
            continue
        lineage.append({"stage": stage, "sql": sql})
        previous = sql

    for index, attempt in enumerate(trace.correction_attempts, start=1):
        corrected = attempt.get("corrected_bound_sql") or attempt.get("corrected_sql")
        if corrected:
            lineage.append({"stage": f"b1_correction_{index}", "sql": str(corrected)})
    for index, attempt in enumerate(trace.execution_recovery_attempts, start=1):
        corrected = attempt.get("corrected_bound_sql") or attempt.get("corrected_sql")
        if corrected:
            lineage.append({"stage": f"b2_recovery_{index}", "sql": str(corrected)})
    return lineage


def _outcome_summary(response: QueryResponse) -> str:
    if response.status == "completed":
        return "The question was resolved, governed, validated, policy-checked, and executed."
    if response.status == "dry_run":
        return "The question was resolved and validated without executing SQL."
    if response.status == "ambiguous":
        return response.message or "A governed clarification is required before execution."
    return response.message or "The question was rejected before execution."
