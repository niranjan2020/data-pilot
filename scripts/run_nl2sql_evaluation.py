"""Repeatable NL-to-SQL evaluation runner; standard-library only.

Cases are source-neutral and require human-approved expectations. The runner
never treats a successful SQL execution as proof of semantic correctness.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen



def _normalized_rows(result: dict) -> list[str]:
    """Canonicalize rows for order-insensitive, type-preserving comparisons."""
    rows = result.get("rows") or []
    if not isinstance(rows, list):
        return []
    return sorted(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
                  for row in rows)


def _result_semantic_checks(case: dict, response: dict) -> list[dict]:
    """Only independently approved result assertions can verify semantics.

    SQL substring checks and HTTP success never establish semantic correctness.
    """
    if case.get("review_status") != "approved" or response.get("status") != "completed":
        return []
    expected = case.get("expected_result")
    # Counts or SQL fragments alone cannot certify a business answer.
    # Require an independently reviewed expected result set.
    if not isinstance(expected, dict) or not isinstance(expected.get("rows"), list):
        return []
    result = response.get("result")
    if not isinstance(result, dict):
        return []
    checks = []
    if "rows" in expected:
        expected_rows = expected["rows"]
        if isinstance(expected_rows, list):
            checks.append({"check": "result_rows", "passed": (
                _normalized_rows(result) == _normalized_rows({"rows": expected_rows})
            )})
    if "row_count" in expected:
        checks.append({"check": "result_row_count", "passed": (
            result.get("row_count", len(result.get("rows") or [])) == expected["row_count"]
        )})
    if "columns" in expected:
        checks.append({"check": "result_columns", "passed": (
            result.get("columns") == expected["columns"]
        )})
    return checks


def evaluate_case(case: dict, response: dict) -> dict:
    expected = case.get("expect") or {}
    status = response.get("status")
    sql = response.get("sql") or ""
    trace = response.get("trace") or {}
    checks = []
    execution_status = (
        "succeeded" if status == "completed" and response.get("result") is not None
        else "api_error" if status == "http_error"
        else "not_executed" if status == "completed"
        else "rejected" if status in ("rejected", "clarification_required", "needs_clarification")
        else "other"
    )
    details = response.get("details") or {}
    error_payload = details.get("detail", details) if isinstance(details, dict) else {}
    error_payload = error_payload if isinstance(error_payload, dict) else {}
    error_info = error_payload.get("details") or {}
    if not isinstance(error_info, dict):
        error_info = {}
    error_codes = [c.get("code") for c in error_info.get("checks", []) if isinstance(c, dict)]
    semantic_checks = _result_semantic_checks(case, response)
    generation_status = (
        "passed" if status in ("dry_run", "completed")
        else "failed" if status in ("http_error", "rejected")
        else "not_verified"
    )
    database_execution_status = (
        "passed" if status == "completed" and response.get("result") is not None
        else "failed" if status == "http_error" and response.get("http_status", 0) >= 500
        else "not_run" if status in ("dry_run", "http_error", "rejected", "clarification_required", "needs_clarification")
        else "not_verified"
    )
    for field, actual in (("status", status),):
        if field in expected:
            checks.append({"check": field, "passed": actual == expected[field]})
    for fragment in expected.get("sql_contains", []):
        checks.append({"check": "sql_contains:" + fragment, "passed": fragment.casefold() in sql.casefold()})
    for fragment in expected.get("sql_excludes", []):
        checks.append({"check": "sql_excludes:" + fragment, "passed": fragment.casefold() not in sql.casefold()})
    if "min_rows" in expected:
        result = response.get("result") or {}
        count = result.get("row_count")
        if count is None:
            count = len(result.get("rows") or [])
        checks.append({"check": "min_rows", "passed": count >= expected["min_rows"]})
    if "error_code" in expected:
        detail = response.get("details") or {}
        if "detail" in detail and isinstance(detail["detail"], dict):
            detail = detail["detail"].get("details") or detail["detail"]
        codes = [
            item.get("code")
            for item in detail.get("checks", [])
        ]
        checks.append({"check": "error_code", "passed": expected["error_code"] in codes})
    if "row_count_equals" in expected:
        result = response.get("result") or {}
        count = result.get("row_count")
        if count is None:
            count = len(result.get("rows") or [])
        checks.append({"check": "row_count_equals", "passed": count == expected["row_count_equals"]})
    if "trace_field" in expected:
        checks.append({"check": "trace_field", "passed": expected["trace_field"] in trace})
    return {
        "id": case["id"], "question": case["question"],
        "reference_sql": case.get("reference_sql"),
        "duplicate_of": case.get("duplicate_of"),
        "status": status, "sql": sql, "checks": checks,
        "execution_status": execution_status,
        "error_type": error_payload.get("error"),
        "error_message": error_payload.get("message"),
        "error_codes": error_codes,
        "sql_checks_status": ("passed" if checks and all(c["passed"] for c in checks)
                              else "failed" if checks else "not_configured"),
        "semantic_status": ("not_verified" if not semantic_checks
                            else "passed" if all(c["passed"] for c in semantic_checks)
                            else "failed"),
        "semantic_checks": semantic_checks,
        "generation_status": generation_status,
        "database_execution_status": database_execution_status,
        "verdict": ("unreviewed" if not checks else
                    "pass" if all(item["passed"] for item in checks) else "needs_review"),
        "response": response,
    }


def request_case(base_url: str, source: str, case: dict, timeout: int, dry_run: bool) -> dict:
    payload = json.dumps({
        "question": case["question"], "source_name": source, "dry_run": dry_run,
    }).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + "/api/query", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            detail = json.load(exc)
        except (ValueError, UnicodeError):
            detail = {"message": "HTTP request failed"}
        return {"status": "http_error", "http_status": exc.code, "details": detail}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run governed NL-to-SQL evaluation cases")
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--source", required=True, help="Existing onboarded data-source name")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--output", type=Path, default=Path("evaluation-results.json"))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--markdown", type=Path, help="Write readable Markdown report")
    parser.add_argument("--execute", action="store_true", help="Execute read-only queries (default: dry run)")
    parser.add_argument("--replay", type=Path, help="Re-evaluate stored responses offline; makes zero API/LLM calls")
    parser.add_argument("--ids", help="Comma-separated case IDs to run (avoids unnecessary LLM calls)")
    parser.add_argument("--max-cases", type=int, help="Maximum number of selected cases to run")
    args = parser.parse_args()
    if args.cases.suffix.lower() == '.csv':
        with args.cases.open(encoding='utf-8-sig', newline='') as stream:
            cases = list(csv.DictReader(stream))
        for case in cases:
            raw = case.get('expect') or ''
            case['expect'] = json.loads(raw) if raw.strip() else {}
    else:
        cases = json.loads(args.cases.read_text(encoding='utf-8-sig'))
    if not isinstance(cases, list):
        parser.error("Case file must be a JSON array")
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        parser.error("Case IDs must be unique")
    if args.ids:
        requested = [item.strip() for item in args.ids.split(",") if item.strip()]
        unknown = set(requested) - set(ids)
        if unknown:
            parser.error("Unknown case IDs: " + ", ".join(sorted(unknown)))
        cases = [case for case in cases if case["id"] in set(requested)]
    if args.max_cases is not None:
        if args.max_cases < 1:
            parser.error("--max-cases must be at least 1")
        cases = cases[:args.max_cases]
    if args.replay:
        print("Replaying {} stored cases offline; zero API/LLM calls.".format(len(cases)))
    else:
        print("Selected {} live evaluation cases; each may incur LLM charges.".format(len(cases)))
    replay_responses = None
    if args.replay:
        replay_data = json.loads(args.replay.read_text(encoding="utf-8-sig"))
        if not isinstance(replay_data, dict) or not isinstance(replay_data.get("results"), list):
            parser.error("--replay must contain an evaluation report with a results array")
        replay_responses = {item["id"]: item["response"] for item in replay_data["results"]
                            if isinstance(item, dict) and "id" in item and isinstance(item.get("response"), dict)}
        missing = [case["id"] for case in cases if case["id"] not in replay_responses]
        if missing:
            parser.error("Missing stored responses for case IDs: " + ", ".join(missing))
    results = []
    endpoint = args.base_url.rstrip("/") + "/api/query"
    for case in cases:
        if not case.get("question"):
            results.append({"id": case["id"], "verdict": "not_configured", "question": case.get("question")})
            continue
        try:
            response = (replay_responses[case["id"]] if replay_responses is not None
                        else request_case(args.base_url, args.source, case, args.timeout, not args.execute))
            results.append(evaluate_case(case, response))
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", None)
            detail = str(reason if reason is not None else exc)
            results.append({
                "id": case["id"], "verdict": "transport_error",
                "error_type": type(exc).__name__, "reason": detail, "endpoint": endpoint,
            })
            print("Cannot connect to {}: {}: {}".format(endpoint, type(exc).__name__, detail))
            print("Stopping evaluation after the first connection failure.")
            break
    summary = {key: sum(x["verdict"] == key for x in results)
               for key in ("pass", "needs_review", "unreviewed", "not_configured", "transport_error")}
    execution_summary = {key: sum(x.get("execution_status") == key for x in results)
                         for key in ("succeeded", "api_error", "rejected", "not_executed", "other")}
    semantic_summary = {key: sum(x.get("semantic_status") == key for x in results)
                        for key in ("passed", "failed", "not_verified")}
    generation_summary = {key: sum(x.get("generation_status") == key for x in results)
                          for key in ("passed", "failed", "not_verified")}
    database_execution_summary = {key: sum(x.get("database_execution_status") == key for x in results)
                                  for key in ("passed", "failed", "not_run", "not_verified")}
    report = {
        "generation_summary": generation_summary,
        "database_execution_summary": database_execution_summary,
        "execution_summary": execution_summary, "semantic_summary": semantic_summary,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": args.source, "mode": "replay" if args.replay else "execute" if args.execute else "dry_run",
        "summary": summary, "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if args.markdown:
        lines = ["# NL-to-SQL evaluation", "", "## Summary", ""]
        lines.extend("- {}: {}".format(k, v) for k, v in summary.items())
        lines.extend(["", "## SQL generation and validation", ""])
        lines.extend("- {}: {}".format(k, v) for k, v in generation_summary.items())
        lines.extend(["", "## Database execution (separate from dry runs)", ""])
        lines.extend("- {}: {}".format(k, v) for k, v in database_execution_summary.items())
        lines.extend(["", "## Execution outcomes", ""])
        lines.extend("- {}: {}".format(k, v) for k, v in execution_summary.items())
        lines.extend(["", "## Semantic verification", ""])
        lines.extend("- {}: {}".format(k, v) for k, v in semantic_summary.items())
        lines.extend(["", "| ID | Verdict | Execution | Semantic | Error codes | Checks |",
                      "|---|---|---|---|---|---|"])
        for item in results:
            checks = item.get("checks") or []
            passed = sum(bool(check.get("passed")) for check in checks)
            lines.append("| {} | {} | {} | {} | {} | {}/{} |".format(
                item["id"], item["verdict"], item.get("execution_status") or "-",
                item.get("semantic_status") or "-",
                ", ".join(item.get("error_codes") or []) or "-",
                passed, len(checks),
            ))
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    print("Report:", args.output)
    return 1 if summary["needs_review"] or summary["transport_error"] or summary["not_configured"] or summary["unreviewed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
