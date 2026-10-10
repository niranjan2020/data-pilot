"""End-to-end deterministic detection and repair of collapsed global comparisons."""
import pytest
from sqlglot import exp, parse_one

from datapilot.application.services.query_correctness import assess_query_correctness
from datapilot.application.services.comparison_group_repair import repair_missing_comparison_groups


def evaluate(sql, question="Compare owned versus chartered records"):
    return assess_query_correctness(
        affected_tables=["public.records"],
        governed_tables=["public.records"],
        sql=sql,
        question=question,
    )


def comparison(checks):
    return [c for c in checks if c["code"] in (
        "comparison_dimension_violation", "comparison_dimension_alignment",
    )]


@pytest.mark.parametrize("measure", [
    "COUNT(*)",
    "COUNT(DISTINCT id)",
    "SUM(amount)",
    "AVG(amount)",
    "MIN(amount)",
    "MAX(amount)",
    "COUNT(*) AS total",
    "SUM(amount) AS total",
])
def test_global_comparison_is_detected_repaired_and_revalidated(measure):
    sql = (
        f"SELECT {measure} FROM public.records "
        "WHERE ownership_status IN ('owned','chartered')"
    )
    checks = evaluate(sql)
    assert len(comparison(checks)) == 1
    assert comparison(checks)[0]["status"] == "failed"
    repaired = repair_missing_comparison_groups(sql, checks, dialect="postgresql")
    assert repaired is not None
    ast = parse_one(repaired, read="postgres")
    assert {c.name for c in ast.args["group"].find_all(exp.Column)} == {"ownership_status"}
    assert any(c.name == "ownership_status" for p in ast.expressions for c in p.find_all(exp.Column))
    assert comparison(evaluate(repaired))[0]["status"] == "passed"


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) FROM public.records JOIN public.details ON records.id=details.id WHERE ownership_status IN ('owned','chartered')",
    "SELECT DISTINCT COUNT(*) FROM public.records WHERE ownership_status IN ('owned','chartered')",
    "SELECT COUNT(*) FROM public.records WHERE ownership_status='owned'",
    "SELECT COUNT(*) FROM public.records",
    "SELECT COUNT(*), region FROM public.records WHERE ownership_status IN ('owned','chartered')",
    "SELECT region FROM public.records WHERE ownership_status IN ('owned','chartered')",
])
def test_unsafe_global_comparisons_do_not_get_repaired(sql):
    checks = evaluate(sql)
    assert repair_missing_comparison_groups(sql, checks, dialect="postgresql") is None


def test_combined_intent_does_not_force_comparison_groups():
    sql = "SELECT COUNT(*) FROM public.records WHERE ownership_status IN ('owned','chartered')"
    assert comparison(evaluate(sql, "Show the combined total of owned and chartered records")) == []


def test_unrelated_question_does_not_force_comparison_groups():
    sql = "SELECT COUNT(*) FROM public.records WHERE ownership_status IN ('owned','chartered')"
    assert comparison(evaluate(sql, "Show record count")) == []


def test_conditional_aggregates_already_preserve_two_cohorts_without_group_by():
    sql = (
        "SELECT COUNT(*) FILTER (WHERE ownership_status='owned') AS owned, "
        "COUNT(*) FILTER (WHERE ownership_status='chartered') AS chartered "
        "FROM public.records WHERE ownership_status IN ('owned','chartered')"
    )
    checks = evaluate(sql)
    assert comparison(checks)[0]["status"] == "passed"
    assert repair_missing_comparison_groups(sql, checks) is None


def test_other_failed_correctness_check_blocks_repair():
    sql = "SELECT COUNT(*) FROM public.records WHERE ownership_status IN ('owned','chartered')"
    checks = evaluate(sql) + [{"code": "metric_expression_violation", "status": "failed"}]
    assert repair_missing_comparison_groups(sql, checks) is None
