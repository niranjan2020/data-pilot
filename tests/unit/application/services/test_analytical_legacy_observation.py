"""Legacy dry-run observation never masquerades as typed plan accuracy."""
from dataclasses import replace

import pytest

from datapilot.application.services.analytical_evaluation import AnalyticalEvaluationCase
from datapilot.application.services.analytical_golden_questions import (
    GoldenAnalyticalQuestion, GoldenCaseStatus,
)
from datapilot.application.services.analytical_legacy_observation import (
    observe_legacy_query_dry_run,
)
from datapilot.application.services.analytical_plan import AnalyticalOperation as Op
from datapilot.domain.query import QueryResponse


def golden():
    return GoldenAnalyticalQuestion(
        expectation=AnalyticalEvaluationCase(
            case_id="sample", question="Top 10 items by count",
            expected_operations=(Op.GROUP, Op.AGGREGATE, Op.SORT, Op.LIMIT),
        ), domain="sample", status=GoldenCaseStatus.SUPPORTED,
    )


class FakeOrchestrator:
    def __init__(self, response):
        self.response = response
        self.requests = []
    async def query(self, request):
        self.requests.append(request)
        return self.response


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["dry_run", "ambiguous", "rejected"])
async def test_legacy_observation_is_non_executing(status):
    response = QueryResponse(
        question=golden().expectation.question, status=status,
        sql="SELECT 1" if status == "dry_run" else None,
    )
    orchestrator = FakeOrchestrator(response)
    observation = await observe_legacy_query_dry_run(
        case=golden(), datasource="sample", orchestrator=orchestrator,
    )
    assert len(orchestrator.requests) == 1
    assert orchestrator.requests[0].dry_run is True
    assert orchestrator.requests[0].source_name == "sample"
    assert observation.case_id == "sample"
    assert observation.typed_plan_available is False
    assert observation.reason == "legacy_query_has_no_typed_analytical_plan"
    assert observation.sql == ("SELECT 1" if status == "dry_run" else None)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "dry_run"])
async def test_execution_results_never_accepted(status):
    response = QueryResponse(
        question=golden().expectation.question, status=status,
        result={"rows": [[1]]},
    )
    with pytest.raises(ValueError, match="execution|completed"):
        await observe_legacy_query_dry_run(
            case=golden(), datasource="sample",
            orchestrator=FakeOrchestrator(response),
        )


@pytest.mark.asyncio
async def test_completed_status_always_rejected():
    with pytest.raises(ValueError, match="completed"):
        await observe_legacy_query_dry_run(
            case=golden(), datasource="sample",
            orchestrator=FakeOrchestrator(QueryResponse(
                question=golden().expectation.question, status="completed",
            )),
        )


@pytest.mark.asyncio
async def test_wrong_question_rejected():
    with pytest.raises(ValueError, match="mismatch"):
        await observe_legacy_query_dry_run(
            case=golden(), datasource="sample",
            orchestrator=FakeOrchestrator(QueryResponse(
                question="different", status="dry_run",
            )),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, object()])
async def test_invalid_orchestrator_rejected(invalid):
    with pytest.raises(ValueError, match="orchestrator"):
        await observe_legacy_query_dry_run(
            case=golden(), datasource="sample", orchestrator=invalid,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["", " "])
async def test_missing_datasource_rejected(invalid):
    with pytest.raises(ValueError, match="Datasource"):
        await observe_legacy_query_dry_run(
            case=golden(), datasource=invalid,
            orchestrator=FakeOrchestrator(None),
        )


@pytest.mark.asyncio
async def test_invalid_response_type_rejected():
    with pytest.raises(ValueError, match="response"):
        await observe_legacy_query_dry_run(
            case=golden(), datasource="sample",
            orchestrator=FakeOrchestrator({"status": "dry_run"}),
        )


@pytest.mark.asyncio
async def test_invalid_case_rejected():
    with pytest.raises(ValueError, match="golden"):
        await observe_legacy_query_dry_run(
            case=None, datasource="sample",
            orchestrator=FakeOrchestrator(None),
        )
