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


def test_correctness_passes_required_grouping_dimension():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Sales.SalesOrderDetail"],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
        sql='SELECT "p"."Name", SUM("d"."LineTotal") FROM "Production"."Product" p JOIN "Sales"."SalesOrderDetail" d ON p."ProductID" = d."ProductID" GROUP BY "p"."Name"',
        required_grouping_columns=["Name"],
    )
    grouping = next(check for check in checks if check["code"] == "grouping_dimension_alignment")
    assert grouping["status"] == "passed"


def test_correctness_rejects_missing_required_grouping_dimension():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Sales.SalesOrderDetail"],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
        sql='SELECT "p"."Color", SUM("d"."LineTotal") FROM "Production"."Product" p JOIN "Sales"."SalesOrderDetail" d ON p."ProductID" = d."ProductID" GROUP BY "p"."Color"',
        required_grouping_columns=["Name"],
    )
    grouping = next(check for check in checks if check["code"] == "grouping_dimension_violation")
    assert grouping["status"] == "failed"
    assert grouping["missing_columns"] == ["name"]


def test_correctness_accepts_additional_grouping_when_required_dimension_is_present():
    checks = assess_query_correctness(
        affected_tables=["Production.Product"],
        governed_tables=["Production.Product"],
        sql='SELECT "Name", "Color", COUNT(*) FROM "Production"."Product" GROUP BY "Name", "Color"',
        required_grouping_columns=["Name"],
    )
    assert any(check["code"] == "grouping_dimension_alignment" for check in checks)


def test_correctness_passes_governed_filter():
    checks = assess_query_correctness(
        affected_tables=["Production.Product"],
        governed_tables=["Production.Product"],
        sql='SELECT "Name" FROM "Production"."Product" WHERE "Color" = \'Red\'',
        required_filters=[{
            "attribute": "Color",
            "column_name": "Color",
            "operator": "=",
            "value": "Red",
        }],
    )
    check = next(item for item in checks if item["code"] == "filter_alignment")
    assert check["status"] == "passed"


def test_correctness_rejects_missing_governed_filter():
    checks = assess_query_correctness(
        affected_tables=["Production.Product"],
        governed_tables=["Production.Product"],
        sql='SELECT "Name" FROM "Production"."Product"',
        required_filters=[{
            "attribute": "Color",
            "column_name": "Color",
            "operator": "=",
            "value": "Red",
        }],
    )
    check = next(item for item in checks if item["code"] == "filter_violation")
    assert check["status"] == "failed"


def test_correctness_rejects_wrong_governed_filter_value():
    checks = assess_query_correctness(
        affected_tables=["Production.Product"],
        governed_tables=["Production.Product"],
        sql='SELECT "Name" FROM "Production"."Product" WHERE "Color" = \'Blue\'',
        required_filters=[{
            "attribute": "Color",
            "column_name": "Color",
            "operator": "=",
            "value": "Red",
        }],
    )
    check = next(item for item in checks if item["code"] == "filter_violation")
    assert check["expected_value"] == "Red"


def test_correctness_accepts_qualified_governed_filter():
    checks = assess_query_correctness(
        affected_tables=["Production.Product"],
        governed_tables=["Production.Product"],
        sql='SELECT "p"."Name" FROM "Production"."Product" p WHERE "p"."Color" = \'Red\'',
        required_filters=[{
            "attribute": "Color",
            "column_name": "Color",
            "operator": "=",
            "value": "Red",
        }],
    )
    assert any(item["code"] == "filter_alignment" for item in checks)
