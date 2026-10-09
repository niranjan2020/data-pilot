"""Offline runner tests: opt-in predictions and fail-closed publication gates."""
from dataclasses import replace

import pytest

from datapilot.application.services.analytical_evaluation import (
    AnalyticalEvaluationCase, AnalyticalEvaluationResult,
)
from datapilot.application.services.analytical_golden_questions import (
    GoldenAnalyticalQuestion, GoldenCaseStatus,
)
from datapilot.application.services.analytical_golden_runner import run_offline_golden_evaluation
from datapilot.application.services.analytical_plan import AnalyticalOperation as Op


class Provider:
    async def get_data_source_id(self, name):
        return 7 if name == "test" else None
    async def list_semantic_entities(self, source_id):
        return [{"id": 1, "name": "Items", "schema_name": "public",
                 "table_name": "items", "attributes": [
                     {"name": "Group", "column_name": "group_code"},
                 ]}]
    async def list_semantic_metrics(self, source_id):
        return [{"id": 2, "name": "Count"}]
    async def list_time_dimensions(self, source_id):
        return []


class Store:
    def __init__(self, grants):
        self.grants = grants
    async def is_published(self, *args):
        return args in self.grants


def gold(case_id, *, pending=False, metric="Count"):
    return GoldenAnalyticalQuestion(
        expectation=AnalyticalEvaluationCase(
            case_id=case_id, question="Count items by group",
            expected_operations=(Op.GROUP, Op.AGGREGATE, Op.SORT, Op.LIMIT),
            expected_dimensions=("Items.Group",),
            expected_metrics=(metric, metric),
            expected_source=("public", "items"),
        ),
        domain="test",
        status=GoldenCaseStatus.PENDING if pending else GoldenCaseStatus.SUPPORTED,
        required_capabilities=("join",) if pending else (),
    )


def arguments(*, publish_metric=True, publish_attribute=True):
    return {
        "datasource": "test", "provider": Provider(),
        "publication_store": Store({(7, "metric", 2)} if publish_metric else set()),
        "attribute_publication_store": Store({(7, 1, "Group")} if publish_attribute else set()),
    }


@pytest.mark.asyncio
async def test_default_mode_never_calls_prediction_adapter():
    calls = []
    async def adapter(case):
        calls.append(case.expectation.case_id)
        return AnalyticalEvaluationResult(case.expectation.case_id, True, ())
    result = await run_offline_golden_evaluation(
        cases=(gold("a"),), prediction_adapter=adapter, **arguments(),
    )
    assert calls == []
    assert result.report.not_evaluated == 1
    assert result.predictions_collected == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["pass", "fail", "missing", "error", "wrong_id", "bad_type", "invalid"])
async def test_opt_in_prediction_outcomes(mode):
    async def adapter(case):
        if mode == "pass":
            return AnalyticalEvaluationResult("a", True, ())
        if mode == "fail":
            return AnalyticalEvaluationResult("a", False, ("metric_mismatch",))
        if mode == "missing":
            return None
        if mode == "error":
            raise RuntimeError("secret internal exception")
        if mode == "wrong_id":
            return AnalyticalEvaluationResult("wrong", True, ())
        if mode == "bad_type":
            return {"passed": True}
        return AnalyticalEvaluationResult("a", True, ("invalid",))
    result = await run_offline_golden_evaluation(
        cases=(gold("a"),), prediction_adapter=adapter,
        enable_predictions=True, **arguments(),
    )
    report = result.report
    if mode == "pass":
        assert (report.passed, report.failed, report.not_evaluated) == (1, 0, 0)
    elif mode == "missing":
        assert (report.passed, report.failed, report.not_evaluated) == (0, 0, 1)
    else:
        assert report.failed == 1
        if mode not in ("fail",):
            assert report.cases[0].reasons == ("prediction_adapter_error",)


@pytest.mark.asyncio
@pytest.mark.parametrize("publish_metric,publish_attribute", [(False, True), (True, False), (False, False)])
async def test_unpublished_metadata_prevents_adapter_calls(publish_metric, publish_attribute):
    calls = []
    async def adapter(case):
        calls.append(case)
        return AnalyticalEvaluationResult(case.expectation.case_id, True, ())
    result = await run_offline_golden_evaluation(
        cases=(gold("a"),), prediction_adapter=adapter, enable_predictions=True,
        **arguments(publish_metric=publish_metric, publish_attribute=publish_attribute),
    )
    assert result.report.blocked == 1
    assert calls == []


@pytest.mark.asyncio
async def test_pending_capability_prevents_adapter_calls():
    async def adapter(case):
        raise AssertionError("Must not be called")
    result = await run_offline_golden_evaluation(
        cases=(gold("a", pending=True),), prediction_adapter=adapter,
        enable_predictions=True, **arguments(),
    )
    assert result.report.blocked == 1


@pytest.mark.asyncio
async def test_mixed_batch_only_evaluates_ready_cases():
    calls = []
    async def adapter(case):
        calls.append(case.expectation.case_id)
        return AnalyticalEvaluationResult(case.expectation.case_id, True, ())
    result = await run_offline_golden_evaluation(
        cases=(gold("a"), gold("b", pending=True), gold("c", metric="Unpublished")),
        prediction_adapter=adapter, enable_predictions=True, **arguments(),
    )
    assert calls == ["a"]
    assert (result.report.passed, result.report.blocked) == (1, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, 1, "yes"])
async def test_non_boolean_opt_in_rejected(invalid):
    with pytest.raises(ValueError, match="boolean"):
        await run_offline_golden_evaluation(
            cases=(gold("a"),), enable_predictions=invalid, **arguments(),
        )


@pytest.mark.asyncio
async def test_enabled_mode_requires_adapter():
    with pytest.raises(ValueError, match="adapter"):
        await run_offline_golden_evaluation(
            cases=(gold("a"),), enable_predictions=True, **arguments(),
        )


@pytest.mark.asyncio
async def test_unknown_datasource_fails_before_prediction():
    async def adapter(case):
        raise AssertionError("Must not run")
    with pytest.raises(ValueError, match="Unknown datasource"):
        await run_offline_golden_evaluation(
            cases=(gold("a"),), datasource="unknown",
            provider=Provider(), publication_store=Store(set()),
            attribute_publication_store=Store(set()),
            enable_predictions=True, prediction_adapter=adapter,
        )


@pytest.mark.asyncio
async def test_duplicate_cases_fail_before_prediction():
    async def adapter(case):
        raise AssertionError("Must not run")
    with pytest.raises(ValueError, match="Duplicate"):
        await run_offline_golden_evaluation(
            cases=(gold("a"), gold("a")), enable_predictions=True,
            prediction_adapter=adapter, **arguments(),
        )
