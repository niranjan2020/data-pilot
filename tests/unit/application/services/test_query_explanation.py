"""Tests for deterministic query explanations."""

from datapilot.application.services.query_explanation import build_query_explanation
from datapilot.domain.query import (
    ClarificationOption,
    ClarificationRequest,
    QueryRejection,
    QueryResponse,
    QueryTrace,
)


def test_completed_explanation_uses_governed_trace_without_llm_messages() -> None:
    trace = QueryTrace(
        retrieved_candidates=[
            {"kind": "entity", "name": "Customer", "decision": "selected", "score": 0.9},
            {"kind": "entity", "name": "Product", "decision": "rejected", "score": 0.8},
        ],
        governed_datasets=["sales.customers"],
        governed_entities=["Customer"],
        governed_metrics=["Revenue"],
        generated_sql="SELECT id FROM customers",
        bound_sql="SELECT id FROM sales.customers",
        validated_sql="SELECT id FROM sales.customers",
        correctness_checks=[{"code": "physical_scope_alignment", "status": "passed"}],
        policy_sql="SELECT id FROM sales.customers LIMIT 100",
        resource_budget={"timeout_seconds": 30.0, "max_result_rows": 100},
        execution={"row_count": 3, "execution_time_ms": 5.0},
        llm_messages=[{"role": "system", "content": "private admin diagnostic"}],
    )
    response = QueryResponse(
        question="show customers",
        status="completed",
        source="generator",
        sql="SELECT id FROM sales.customers LIMIT 100",
        trace=trace,
    )

    explanation = build_query_explanation(response)

    assert explanation.outcome == "completed"
    assert explanation.governed_interpretation["entities"] == ["Customer"]
    assert explanation.resource_policy["timeout_seconds"] == 30.0
    assert [item["stage"] for item in explanation.sql_lineage] == [
        "generated", "bound", "policy"
    ]
    serialized = explanation.model_dump_json()
    assert "private admin diagnostic" not in serialized
    assert "Customer" in serialized
    assert any(step.stage == "correctness" and step.status == "passed" for step in explanation.steps)
    assert any(step.stage == "execution" and step.status == "executed" for step in explanation.steps)


def test_ambiguous_explanation_records_governed_clarification() -> None:
    response = QueryResponse(
        question="show activity",
        status="ambiguous",
        clarification=ClarificationRequest(
            kind="entity",
            key="entity",
            question="Which business entity do you mean?",
            options=[
                ClarificationOption(value="Customer", label="Customer"),
                ClarificationOption(value="Product", label="Product"),
            ],
        ),
        trace=QueryTrace(governed_entities=["Customer", "Product"]),
        message="I found more than one governed entity that could match this question.",
    )

    explanation = build_query_explanation(response)

    step = next(step for step in explanation.steps if step.stage == "clarification")
    assert step.status == "clarification_required"
    assert step.evidence["options"] == ["Customer", "Product"]
    assert explanation.sql_lineage == []


def test_rejected_explanation_records_structured_rejection_without_sql() -> None:
    response = QueryResponse(
        question="show secret payroll",
        status="rejected",
        rejection=QueryRejection(
            code="unsupported_question",
            reason="The question could not be mapped to a governed entity.",
        ),
        trace=QueryTrace(governed_entities=["Customer"]),
        message="I could not map this question to a governed business entity. No SQL was generated.",
    )

    explanation = build_query_explanation(response)

    outcome = next(step for step in explanation.steps if step.stage == "outcome")
    assert outcome.status == "rejected"
    assert outcome.evidence["code"] == "unsupported_question"
    assert explanation.sql_lineage == []


def test_explanation_records_b1_and_b2_lineage() -> None:
    trace = QueryTrace(
        generated_sql="SELECT wrong FROM records",
        correction_attempts=[{
            "corrected_sql": "SELECT missing FROM records",
            "corrected_bound_sql": "SELECT missing FROM public.records",
        }],
        execution_recovery_attempts=[{
            "corrected_sql": "SELECT id FROM records",
            "corrected_bound_sql": "SELECT id FROM public.records",
        }],
        policy_sql="SELECT id FROM public.records LIMIT 100",
    )
    response = QueryResponse(
        question="show records",
        status="completed",
        source="generator",
        trace=trace,
    )

    explanation = build_query_explanation(response)

    stages = [item["stage"] for item in explanation.sql_lineage]
    assert stages == ["generated", "policy", "b1_correction_1", "b2_recovery_1"]
    assert any(step.stage == "correction" and step.status == "corrected" for step in explanation.steps)
    assert any(step.stage == "recovery" and step.status == "recovered" for step in explanation.steps)
