"""Evaluation runner contract tests: no LLM, database, or network needed."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("evaluation_runner", ROOT / "scripts" / "run_nl2sql_evaluation.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_benchmark_manifest_has_38_unique_slots():
    cases = json.loads((ROOT / "evaluations" / "astra_38_template.json").read_text(encoding="utf-8"))
    assert len(cases) == 38  # provisional slots pending original question import
    assert len({case["id"] for case in cases}) == 38
    assert all(not case["question"] and case["expect"] is None for case in cases)


def test_status_and_sql_constraints_pass():
    case = {"id": "generic", "question": "show records",
            "expect": {"status": "completed", "sql_contains": ["CARDINALITY("],
                       "sql_excludes": ["IS NOT NULL"]}}
    result = runner.evaluate_case(case, {"status": "completed", "sql": "SELECT CARDINALITY(tags) > 0"})
    assert result["verdict"] == "pass"


def test_execution_without_expectations_remains_unreviewed():
    result = runner.evaluate_case({"id": "x", "question": "q"}, {"status": "completed", "sql": "SELECT 1"})
    assert result["verdict"] == "unreviewed"


def test_failed_sql_expectation_needs_review():
    case = {"id": "x", "question": "q", "expect": {"sql_contains": ["CARDINALITY("]}}
    result = runner.evaluate_case(case, {"status": "completed", "sql": "SELECT 1"})
    assert result["verdict"] == "needs_review"


def test_min_rows_checks_result_rows():
    case = {"id": "x", "question": "q", "expect": {"min_rows": 2}}
    assert runner.evaluate_case(case, {"result": {"rows": [[1], [2]]}})["verdict"] == "pass"
    assert runner.evaluate_case(case, {"result": {"rows": [[1]]}})["verdict"] == "needs_review"


def test_expected_error_code_matches_details():
    case = {"id": "x", "question": "q", "expect": {"error_code": "metric_missing"}}
    response = {"details": {"checks": [{"code": "metric_missing"}]}}
    assert runner.evaluate_case(case, response)["verdict"] == "pass"


def test_unreviewed_case_keeps_reference_sql_without_approving_it():
    case = {"id": "case-1", "question": "Show records",
            "reference_sql": "SELECT * FROM records", "expect": {},
            "duplicate_of": "case-0"}
    result = runner.evaluate_case(case, {"status": "completed", "sql": "SELECT id FROM records"})
    assert result["verdict"] == "unreviewed"
    assert result["reference_sql"] == "SELECT * FROM records"
    assert result["duplicate_of"] == "case-0"
    assert result["sql"] == "SELECT id FROM records"


def test_error_response_preserved_for_diagnostics():
    case = {"id": "case-2", "question": "Show records", "expect": {}}
    response = {"status": "http_error", "http_status": 422,
                "details": {"detail": {"error": "SQLValidationError"}}}
    result = runner.evaluate_case(case, response)
    assert result["verdict"] == "unreviewed"
    assert result["response"]["http_status"] == 422
