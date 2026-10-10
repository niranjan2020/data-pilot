"""Offline evaluation contracts: generation, execution, and semantics differ."""
from pathlib import Path
import runpy

evaluate_case = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts" / "run_nl2sql_evaluation.py")
)["evaluate_case"]


def test_dry_run_never_counts_as_executed_or_semantically_verified():
    case = {"id": "generic-1", "question": "Count products", "review_status": "approved",
            "expected_result": {"rows": [{"count": 2}]}}
    result = evaluate_case(case, {"status": "dry_run", "sql": "SELECT COUNT(*) FROM public.products"})
    assert result["generation_status"] == "passed"
    assert result["database_execution_status"] == "not_run"
    assert result["semantic_status"] == "not_verified"


def test_approved_expected_rows_can_verify_executed_results():
    case = {"id": "generic-2", "question": "Count products", "review_status": "approved",
            "expected_result": {"rows": [{"count": 2}], "row_count": 1}}
    response = {"status": "completed", "sql": "SELECT COUNT(*) FROM public.products",
                "result": {"rows": [{"count": 2}], "row_count": 1}}
    result = evaluate_case(case, response)
    assert result["generation_status"] == "passed"
    assert result["database_execution_status"] == "passed"
    assert result["semantic_status"] == "passed"
    response["result"]["rows"][0]["count"] = 3
    assert evaluate_case(case, response)["semantic_status"] == "failed"


def test_sql_contains_never_proves_semantics_even_when_approved():
    case = {"id": "generic-3", "question": "Count products", "review_status": "approved",
            "expect": {"sql_contains": ["COUNT"]}}
    result = evaluate_case(case, {"status": "completed", "sql": "SELECT COUNT(*)",
                                  "result": {"rows": [{"count": 1}], "row_count": 1}})
    assert result["sql_checks_status"] == "passed"
    assert result["semantic_status"] == "not_verified"


def test_http_error_is_not_mislabeled_as_database_execution_failure():
    case = {"id": "generic-4", "question": "Count products"}
    result = evaluate_case(case, {"status": "http_error", "http_status": 400,
                                  "details": {"message": "Invalid generated SQL"}})
    assert result["generation_status"] == "failed"
    assert result["database_execution_status"] == "not_run"
