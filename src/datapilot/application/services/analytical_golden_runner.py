"""Opt-in offline golden-question runner with explicit prediction adapter.

The adapter is caller-supplied: this module never connects to an LLM or SQL
executor. Only trusted published metadata gates which questions are eligible.
No live request route is modified.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from datapilot.application.services.analytical_evaluation import AnalyticalEvaluationResult
from datapilot.application.services.analytical_golden_batch import GoldenBatchReport, score_golden_batch
from datapilot.application.services.analytical_golden_loader import evaluate_published_golden_readiness
from datapilot.application.services.analytical_golden_questions import GoldenAnalyticalQuestion


PredictionAdapter = Callable[[GoldenAnalyticalQuestion], Awaitable[AnalyticalEvaluationResult | None]]


@dataclass(frozen=True)
class OfflineGoldenRun:
    report: GoldenBatchReport
    predictions_collected: int


async def run_offline_golden_evaluation(
    *,
    cases: tuple[GoldenAnalyticalQuestion, ...],
    datasource: str,
    provider: Any,
    publication_store: Any,
    attribute_publication_store: Any,
    prediction_adapter: PredictionAdapter | None = None,
    enable_predictions: bool = False,
) -> OfflineGoldenRun:
    """Score real predictions only when explicitly enabled.

    The adapter must return independently evaluated evidence, not a fabricated
    success flag. Adapter exceptions become failed predictions for ready cases;
    governance and metadata-loader exceptions propagate and fail the run.
    """
    if type(enable_predictions) is not bool:
        raise ValueError("enable_predictions must be boolean")
    if enable_predictions and not callable(prediction_adapter):
        raise ValueError("Opt-in prediction runs require a prediction adapter")
    if prediction_adapter is not None and not callable(prediction_adapter):
        raise ValueError("Prediction adapter must be callable")
    readiness = await evaluate_published_golden_readiness(
        cases=cases, datasource=datasource, provider=provider,
        publication_store=publication_store,
        attribute_publication_store=attribute_publication_store,
    )
    predictions: list[AnalyticalEvaluationResult] = []
    if enable_predictions:
        for case, gate in zip(cases, readiness):
            if not gate.ready:
                continue
            case_id = case.expectation.case_id
            try:
                result = await prediction_adapter(case)
                if result is None:
                    continue
                if not isinstance(result, AnalyticalEvaluationResult):
                    raise ValueError("Invalid prediction evidence type")
                if result.case_id != case_id:
                    raise ValueError("Prediction case id mismatch")
                if (result.passed and result.failures) or (
                    not result.passed and not result.failures
                ):
                    raise ValueError("Inconsistent prediction evidence")
            except Exception:
                # Never leak provider or model exception text into reporting.
                result = AnalyticalEvaluationResult(
                    case_id, False, ("prediction_adapter_error",),
                )
            predictions.append(result)
    report = score_golden_batch(cases, readiness, tuple(predictions))
    return OfflineGoldenRun(report=report, predictions_collected=len(predictions))
