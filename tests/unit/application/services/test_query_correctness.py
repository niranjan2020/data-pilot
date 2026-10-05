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


def test_correctness_passes_governed_derived_metric_expression():
    checks = assess_query_correctness(
        affected_tables=["Sales.SalesOrderDetail"],
        governed_tables=["Sales.SalesOrderDetail"],
        sql='SELECT SUM("d"."OrderQty" * "d"."UnitPrice" * (1 - "d"."UnitPriceDiscount")) AS revenue FROM "Sales"."SalesOrderDetail" AS "d"',
        governed_metrics=[{
            "name": "Revenue",
            "aggregation": "sum",
            "calculation_expression": '"OrderQty" * "UnitPrice" * (1 - "UnitPriceDiscount")',
        }],
    )
    metric = next(check for check in checks if check["code"] == "metric_expression_alignment")
    assert metric["status"] == "passed"
    assert metric["metric"] == "Revenue"


def test_correctness_rejects_wrong_derived_metric_expression():
    checks = assess_query_correctness(
        affected_tables=["Sales.SalesOrderDetail"],
        governed_tables=["Sales.SalesOrderDetail"],
        sql='SELECT SUM("d"."LineTotal") AS revenue FROM "Sales"."SalesOrderDetail" AS "d"',
        governed_metrics=[{
            "name": "Revenue",
            "aggregation": "sum",
            "calculation_expression": '"OrderQty" * "UnitPrice" * (1 - "UnitPriceDiscount")',
        }],
    )
    metric = next(check for check in checks if check["code"] == "metric_expression_violation")
    assert metric["status"] == "failed"
    assert metric["metric"] == "Revenue"


def test_correctness_rejects_wrong_aggregation_for_derived_metric():
    checks = assess_query_correctness(
        affected_tables=["Sales.SalesOrderDetail"],
        governed_tables=["Sales.SalesOrderDetail"],
        sql='SELECT AVG("OrderQty" * "UnitPrice" * (1 - "UnitPriceDiscount")) AS revenue FROM "Sales"."SalesOrderDetail"',
        governed_metrics=[{
            "name": "Revenue",
            "aggregation": "sum",
            "calculation_expression": '"OrderQty" * "UnitPrice" * (1 - "UnitPriceDiscount")',
        }],
    )
    assert any(check["code"] == "metric_expression_violation" for check in checks)
