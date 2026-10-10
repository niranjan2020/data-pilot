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


def evaluate_case(case: dict, response: dict) -> dict:
    expected = case.get("expect") or {}
    status = response.get("status")
    sql = response.get("sql") or ""
    trace = response.get("trace") or {}
    checks = []
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
    results = []
    endpoint = args.base_url.rstrip("/") + "/api/query"
    for case in cases:
        if not case.get("question"):
            results.append({"id": case["id"], "verdict": "not_configured", "question": case.get("question")})
            continue
        try:
            response = request_case(args.base_url, args.source, case, args.timeout, not args.execute)
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
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": args.source, "mode": "execute" if args.execute else "dry_run",
        "summary": summary, "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if args.markdown:
        lines = ["# NL-to-SQL evaluation", "", "## Summary", ""]
        lines.extend("- {}: {}".format(k, v) for k, v in summary.items())
        lines.extend(["", "| ID | Verdict | API status | Checks |", "|---|---|---|---|"])
        for item in results:
            checks = item.get("checks") or []
            passed = sum(bool(check.get("passed")) for check in checks)
            lines.append("| {} | {} | {} | {}/{} |".format(
                item["id"], item["verdict"], item.get("status") or "-",
                passed, len(checks),
            ))
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    print("Report:", args.output)
    return 1 if summary["needs_review"] or summary["transport_error"] or summary["not_configured"] or summary["unreviewed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
