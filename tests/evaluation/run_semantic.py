"""Run configured semantic retrieval regression cases against Data Pilot."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.application.services.semantic_context import SemanticContextAssembler
from datapilot.core.config import Settings
from datapilot.core.exceptions import (
    ConfigurationError,
    DatabaseExecutionError,
    LLMError,
    MetadataError,
    SemanticRetrievalError,
    SQLGenerationError,
    SQLValidationError,
    TimeInterpretationError,
)
from datapilot.domain.query import QueryRequest
from datapilot.infrastructure.database.postgresql import PostgreSQLDatabaseProvider
from datapilot.infrastructure.llm.gemini import GeminiLLMProvider
from datapilot.infrastructure.metadata.postgresql import PostgreSQLMetadataProvider
from datapilot.infrastructure.metadata.semantic_postgresql import PostgreSQLSemanticCatalogProvider
from datapilot.infrastructure.semantic.qdrant import QdrantSemanticIndex
from datapilot.infrastructure.sql.llm_generator import LLMBackedSQLGenerator
from datapilot.infrastructure.sql.validator import SQLGlotValidator
from datapilot.infrastructure.sql.identifier_binding import SQLGlotIdentifierBinder

from tests.evaluation.harness import (
    EvaluationCase,
    EvaluationExpectation,
    EvaluationResult,
    EvaluationSummary,
    evaluate_query_response,
)


DEFAULT_CASES = Path(__file__).with_name("semantic_cases.json")


def classify_runtime_exception(exc: Exception) -> tuple[str, ...]:
    """Map runtime failures to the narrowest trustworthy evaluation stage."""
    if isinstance(exc, SemanticRetrievalError):
        return ("semantic_retrieval",)
    if isinstance(exc, TimeInterpretationError):
        return ("time_interpretation",)
    if isinstance(exc, DatabaseExecutionError):
        return ("execution",)
    if isinstance(exc, (SQLGenerationError, LLMError)):
        return ("sql_generation",)
    if isinstance(exc, MetadataError):
        return ("semantic_resolution",)
    if isinstance(exc, SQLValidationError):
        details = getattr(exc, "details", {}) or {}
        checks = details.get("checks")
        if checks:
            return ("governed_correctness",)
        return ("validation",)
    return ()


def load_cases(path: Path) -> list[tuple[EvaluationCase, str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases: list[tuple[EvaluationCase, str]] = []
    for item in raw:
        expected = item.get("expected", {})
        case = EvaluationCase(
            id=item["id"],
            question=item["question"],
            expected=EvaluationExpectation(
                tables=tuple(expected.get("tables", [])),
                row_count=expected.get("row_count"),
                scalar=expected.get("scalar"),
                rows=tuple(tuple(row) for row in expected.get("rows", [])),
                datasets=tuple(expected.get("datasets", [])),
                entities=tuple(expected.get("entities", [])),
                relationships=tuple(expected.get("relationships", [])),
                metrics=tuple(expected.get("metrics", [])),
                excluded_datasets=tuple(expected.get("excluded_datasets", [])),
                excluded_entities=tuple(expected.get("excluded_entities", [])),
                excluded_metrics=tuple(expected.get("excluded_metrics", [])),
                require_completed=expected.get("require_completed", False),
                require_sql=expected.get("require_sql", False),
                expected_status=expected.get("expected_status"),
                rejection_code=expected.get("rejection_code"),
                require_no_sql=expected.get("require_no_sql", False),
                clarification_kind=expected.get("clarification_kind"),
                clarification_options=tuple(expected.get("clarification_options", [])),
                sql_contains=tuple(expected.get("sql_contains", [])),
                sql_excludes=tuple(expected.get("sql_excludes", [])),
                required_correctness_codes=tuple(expected.get("required_correctness_codes", [])),
                forbidden_correctness_codes=tuple(expected.get("forbidden_correctness_codes", [])),
            ),
            conversation_id=item.get("conversation_id"),
        )
        cases.append((case, item.get("source_name", "")))
    return cases


async def build_orchestrator(settings: Settings) -> tuple[QueryOrchestrator, list[Any]]:
    if not settings.default_database_url:
        raise ConfigurationError("DEFAULT_DATABASE_URL is required")
    if settings.gemini_api_key is None:
        raise ConfigurationError("GEMINI_API_KEY is required")
    if settings.default_llm_provider != "gemini":
        raise ConfigurationError(
            "The evaluation runner currently has no adapter registered for "
            f"DEFAULT_LLM_PROVIDER={settings.default_llm_provider!r}"
        )

    database = PostgreSQLDatabaseProvider(
        database_url=settings.default_database_url,
        pool_size=settings.database_pool_size,
        default_timeout_seconds=settings.database_query_timeout_seconds,
    )
    metadata_url = settings.metadata_database_url or settings.default_database_url
    semantic_catalog = PostgreSQLSemanticCatalogProvider(
        database_url=metadata_url,
        pool_size=settings.metadata_database_pool_size,
    )
    await semantic_catalog.initialize()
    metadata_catalog = PostgreSQLMetadataProvider(
        database_url=metadata_url,
        pool_size=settings.metadata_database_pool_size,
    )
    llm = GeminiLLMProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
    )
    retriever = QdrantSemanticIndex(
        settings.qdrant_url,
        settings.qdrant_collection,
        settings.embedding_model,
    )
    orchestrator = QueryOrchestrator(
        database_provider=database,
        sql_validator=SQLGlotValidator(),
        sql_generator=LLMBackedSQLGenerator(llm),
        semantic_catalog_provider=semantic_catalog,
        query_timeout_seconds=settings.database_query_timeout_seconds,
        semantic_retriever=retriever,
        semantic_context_assembler=SemanticContextAssembler(metadata_catalog),
        sql_identifier_binder=SQLGlotIdentifierBinder(),
    )
    return orchestrator, [database, semantic_catalog, metadata_catalog]


async def close_resources(resources: list[Any]) -> None:
    for resource in reversed(resources):
        close = getattr(resource, "close", None)
        if close is None:
            continue
        result = close()
        if hasattr(result, "__await__"):
            await result


def print_result(result: EvaluationResult, question: str) -> None:
    marker = "PASS" if result.passed else "FAIL"
    timing = f" ({result.duration_ms:.0f} ms)" if result.duration_ms is not None else ""
    print(f"[{marker}] {result.case_id}: {question}{timing}")
    if result.failure_categories:
        print(f"       category: {', '.join(result.failure_categories)}")
    for failure in result.failures:
        print(f"       - {failure}")


async def run(path: Path, case_id: str | None = None) -> int:
    cases = load_cases(path)
    if case_id is not None:
        cases = [item for item in cases if item[0].id == case_id]
        if not cases:
            raise ValueError(f"Unknown evaluation case: {case_id}")
    settings = Settings()
    orchestrator, resources = await build_orchestrator(settings)
    summary = EvaluationSummary()
    conversation_contexts: dict[str, dict[str, Any]] = {}

    try:
        for case, source_name in cases:
            started = time.perf_counter()
            try:
                conversation_context = (
                    conversation_contexts.get(case.conversation_id, {})
                    if case.conversation_id
                    else {}
                )
                response = await orchestrator.query(
                    QueryRequest(question=case.question, source_name=source_name or None),
                    conversation_context=conversation_context,
                )
                if case.conversation_id and response.status == "completed":
                    trace = response.trace
                    prior_turns = list(conversation_context.get("analytical_turns") or [])
                    prior_turns.append(case.question)
                    conversation_contexts[case.conversation_id] = {
                        "previous_question": case.question,
                        "analytical_turns": prior_turns,
                        "governed_metrics": list(trace.governed_metrics) if trace else [],
                        "governed_entities": list(trace.governed_entities) if trace else [],
                        "clarification_selections": (
                            dict(trace.clarification_selections) if trace else {}
                        ),
                    }
                evaluated = evaluate_query_response(case, response)
                result = EvaluationResult(
                    case_id=evaluated.case_id,
                    passed=evaluated.passed,
                    failures=evaluated.failures,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    failure_categories=evaluated.failure_categories,
                )
            except Exception as exc:
                result = EvaluationResult(
                    case_id=case.id,
                    passed=False,
                    failures=(f"{type(exc).__name__}: {exc}",),
                    duration_ms=(time.perf_counter() - started) * 1000,
                    failure_categories=classify_runtime_exception(exc),
                )
            summary.results.append(result)
            print_result(result, case.question)
    finally:
        await close_resources(resources)

    print()
    print(
        f"Semantic evaluation: {summary.passed}/{summary.total} passed "
        f"({summary.accuracy:.1%}), {summary.failed} failed"
    )
    if summary.p50_ms is not None:
        print(f"Latency: p50 {summary.p50_ms:.0f} ms | p95 {summary.p95_ms:.0f} ms")
    category_counts = {
        category: count
        for category, count in summary.failure_category_counts.items()
        if count
    }
    if category_counts:
        print("Failure categories:")
        for category, count in category_counts.items():
            pass_rate = summary.category_pass_rates[category]
            print(
                f"  {category}: {count}/{summary.total} affected | "
                f"pass rate {pass_rate:.1%}"
            )
    return 0 if summary.failed == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Data Pilot semantic evaluation cases")
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES,
        help=f"Evaluation JSON file (default: {DEFAULT_CASES})",
    )
    parser.add_argument(
        "--case",
        dest="case_id",
        help="Run only one evaluation case by id.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    # psycopg's async connection pool requires a selector-based event loop on
    # Windows. Python defaults to ProactorEventLoop there, so make the
    # standalone evaluation runner use the compatible policy explicitly.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    args = parse_args()
    sys.exit(asyncio.run(run(args.cases)))
