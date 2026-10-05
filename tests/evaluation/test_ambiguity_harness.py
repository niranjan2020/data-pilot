"""Tests for structured ambiguity evaluation assertions."""

from datapilot.domain.query import ClarificationOption, ClarificationRequest, QueryResponse
from tests.evaluation.harness import EvaluationCase, EvaluationExpectation, evaluate_query_response


def test_ambiguity_expectation_accepts_matching_structured_clarification():
    case = EvaluationCase(
        id="ambiguous-region",
        question="Show customers by region",
        expected=EvaluationExpectation(
            expected_status="ambiguous",
            clarification_kind="attribute",
            clarification_options=("Customer.Billing Region", "Customer.Shipping Region"),
        ),
    )
    response = QueryResponse(
        question=case.question,
        status="ambiguous",
        clarification=ClarificationRequest(
            kind="attribute", key="attribute", question="Which region?",
            options=[
                ClarificationOption(value="Customer.Billing Region", label="Billing Region"),
                ClarificationOption(value="Customer.Shipping Region", label="Shipping Region"),
            ],
        ),
    )

    result = evaluate_query_response(case, response)

    assert result.passed
    assert result.failures == ()


def test_ambiguity_expectation_rejects_wrong_clarification_contract():
    case = EvaluationCase(
        id="ambiguous-sales",
        question="Show sales",
        expected=EvaluationExpectation(
            expected_status="ambiguous",
            clarification_kind="metric",
            clarification_options=("Revenue", "Units Sold"),
        ),
    )
    response = QueryResponse(
        question=case.question,
        status="ambiguous",
        clarification=ClarificationRequest(
            kind="entity", key="entity", question="Which entity?",
            options=[ClarificationOption(value="Revenue", label="Revenue")],
        ),
    )

    result = evaluate_query_response(case, response)

    assert not result.passed
    assert any("clarification kind" in failure for failure in result.failures)
    assert any("Units Sold" in failure for failure in result.failures)
