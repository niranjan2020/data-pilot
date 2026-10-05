"""Tests for deterministic pre-execution query correctness checks."""

from datapilot.application.services.query_correctness import assess_query_correctness


def test_correctness_passes_when_affected_tables_are_governed():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Sales.SalesOrderDetail"],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
    )
    assert checks[0]["status"] == "passed"
    assert checks[0]["code"] == "physical_scope_alignment"


def test_correctness_accepts_unqualified_validator_table_name():
    checks = assess_query_correctness(
        affected_tables=["Product"],
        governed_tables=["Production.Product"],
    )
    assert checks[0]["status"] == "passed"


def test_correctness_rejects_table_outside_governed_scope():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Person.Person"],
        governed_tables=["Production.Product"],
    )
    assert checks[0]["status"] == "failed"
    assert checks[0]["code"] == "physical_scope_violation"
    assert checks[0]["unexpected_tables"] == ["Person.Person"]


def test_correctness_skips_when_no_governed_boundary_exists():
    checks = assess_query_correctness(
        affected_tables=["records"],
        governed_tables=[],
    )
    assert checks[0]["status"] == "skipped"
    assert checks[0]["code"] == "governed_scope_unavailable"
