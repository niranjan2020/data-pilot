"""Tests for deterministic pre-execution query correctness checks."""

import pytest

from datapilot.application.services.query_correctness import assess_query_correctness


def test_correctness_passes_when_affected_tables_are_governed():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Sales.SalesOrderDetail"],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
    )
    assert checks[0]["status"] == "passed"
    assert checks[0]["code"] == "physical_scope_alignment"


def test_correctness_accepts_quoted_aliased_validator_table_name():
    checks = assess_query_correctness(
        affected_tables=['"Production"."Product" AS "T1"', '"Sales"."SalesOrderDetail" AS "T2"'],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
    )
    assert checks[0]["status"] == "passed"
    assert checks[0]["code"] == "physical_scope_alignment"


def test_correctness_accepts_quoted_table_without_alias():
    checks = assess_query_correctness(
        affected_tables=['"Production"."Product"'],
        governed_tables=["Production.Product"],
    )
    assert checks[0]["status"] == "passed"


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


def test_correctness_accepts_unquoted_governed_expression_against_quoted_sql():
    checks = assess_query_correctness(
        affected_tables=['"Sales"."SalesOrderDetail" AS "T1"'],
        governed_tables=["Sales.SalesOrderDetail"],
        sql='SELECT SUM("T1"."OrderQty" * "T1"."UnitPrice" * (1 - "T1"."UnitPriceDiscount")) AS revenue FROM "Sales"."SalesOrderDetail" AS "T1"',
        governed_metrics=[{
            "name": "Revenue",
            "aggregation": "sum",
            "calculation_expression": "OrderQty * UnitPrice * (1 - UnitPriceDiscount)",
        }],
    )
    metric = next(check for check in checks if check["code"] == "metric_expression_alignment")
    assert metric["status"] == "passed"


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


def test_correctness_rejects_partial_multi_dimension_grouping():
    checks = assess_query_correctness(
        affected_tables=["public.customers", "public.orders"],
        governed_tables=["public.customers", "public.orders"],
        sql=(
            'SELECT "c"."country", SUM("o"."amount") '
            'FROM "public"."customers" c '
            'JOIN "public"."orders" o ON "c"."customer_id" = "o"."customer_id" '
            'GROUP BY "c"."country"'
        ),
        required_grouping_columns=["country", "segment"],
    )

    violation = next(
        check for check in checks
        if check["code"] == "grouping_dimension_violation"
    )
    assert violation["status"] == "failed"
    assert violation["missing_columns"] == ["segment"]


def test_correctness_accepts_complete_multi_dimension_grouping():
    checks = assess_query_correctness(
        affected_tables=["public.customers", "public.orders"],
        governed_tables=["public.customers", "public.orders"],
        sql=(
            'SELECT "c"."country", "c"."segment", SUM("o"."amount") '
            'FROM "public"."customers" c '
            'JOIN "public"."orders" o ON "c"."customer_id" = "o"."customer_id" '
            'GROUP BY "c"."country", "c"."segment"'
        ),
        required_grouping_columns=["country", "segment"],
    )

    alignment = next(
        check for check in checks
        if check["code"] == "grouping_dimension_alignment"
    )
    assert alignment["status"] == "passed"


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


def _product_line_relationship():
    return [{
        "name": "Sales Order Line to Product",
        "from_entity_id": 20,
        "from_table": "Sales.SalesOrderDetail",
        "from_column": "ProductID",
        "to_entity_id": 10,
        "to_table": "Production.Product",
        "to_column": "ProductID",
        "cardinality": "many-to-one",
    }]


def test_correctness_passes_governed_relationship_join():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Sales.SalesOrderDetail"],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
        sql='SELECT "p"."Name", SUM("d"."LineTotal") FROM "Production"."Product" p JOIN "Sales"."SalesOrderDetail" d ON "p"."ProductID" = "d"."ProductID" GROUP BY "p"."Name"',
        required_relationships=_product_line_relationship(),
    )
    check = next(item for item in checks if item["code"] == "relationship_alignment")
    assert check["status"] == "passed"


def test_correctness_rejects_wrong_governed_relationship_join_columns():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Sales.SalesOrderDetail"],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
        sql='SELECT "p"."Name" FROM "Production"."Product" p JOIN "Sales"."SalesOrderDetail" d ON "p"."ProductID" = "d"."SalesOrderID"',
        required_relationships=_product_line_relationship(),
    )
    check = next(item for item in checks if item["code"] == "relationship_violation")
    assert check["status"] == "failed"


def test_correctness_rejects_missing_governed_relationship_join():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Sales.SalesOrderDetail"],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
        sql='SELECT "p"."Name" FROM "Production"."Product" p CROSS JOIN "Sales"."SalesOrderDetail" d',
        required_relationships=_product_line_relationship(),
    )
    assert any(item["code"] == "relationship_violation" for item in checks)


def test_correctness_accepts_reversed_governed_relationship_equality():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Sales.SalesOrderDetail"],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
        sql='SELECT "p"."Name" FROM "Production"."Product" p JOIN "Sales"."SalesOrderDetail" d ON "d"."ProductID" = "p"."ProductID"',
        required_relationships=_product_line_relationship(),
    )
    assert any(item["code"] == "relationship_alignment" for item in checks)



def _generic_order_dimension_relationships():
    return [
        {
            "name": "Order to Customer",
            "from_entity_id": 203,
            "from_table": "public.orders",
            "from_column": "customer_id",
            "to_entity_id": 201,
            "to_table": "public.customers",
            "to_column": "customer_id",
            "cardinality": "many-to-one",
        },
        {
            "name": "Order to Product",
            "from_entity_id": 203,
            "from_table": "public.orders",
            "from_column": "product_id",
            "to_entity_id": 202,
            "to_table": "public.products",
            "to_column": "product_id",
            "cardinality": "many-to-one",
        },
    ]


def test_correctness_accepts_complete_cross_entity_relationship_path():
    checks = assess_query_correctness(
        affected_tables=["public.customers", "public.orders", "public.products"],
        governed_tables=["public.customers", "public.orders", "public.products"],
        sql=(
            'SELECT "c"."country", "p"."category", SUM("o"."amount") '
            'FROM "public"."orders" o '
            'JOIN "public"."customers" c ON "o"."customer_id" = "c"."customer_id" '
            'JOIN "public"."products" p ON "o"."product_id" = "p"."product_id" '
            'GROUP BY "c"."country", "p"."category"'
        ),
        required_relationships=_generic_order_dimension_relationships(),
    )

    alignment = next(
        check for check in checks
        if check["code"] == "relationship_alignment"
    )
    assert alignment["status"] == "passed"


def test_correctness_rejects_partial_cross_entity_relationship_path():
    checks = assess_query_correctness(
        affected_tables=["public.customers", "public.orders", "public.products"],
        governed_tables=["public.customers", "public.orders", "public.products"],
        sql=(
            'SELECT "c"."country", "p"."category", SUM("o"."amount") '
            'FROM "public"."orders" o '
            'JOIN "public"."customers" c ON "o"."customer_id" = "c"."customer_id" '
            'CROSS JOIN "public"."products" p '
            'GROUP BY "c"."country", "p"."category"'
        ),
        required_relationships=_generic_order_dimension_relationships(),
    )

    violation = next(
        check for check in checks
        if check["code"] == "relationship_violation"
    )
    assert violation["status"] == "failed"


def test_correctness_rejects_wrong_second_cross_entity_join():
    checks = assess_query_correctness(
        affected_tables=["public.customers", "public.orders", "public.products"],
        governed_tables=["public.customers", "public.orders", "public.products"],
        sql=(
            'SELECT "c"."country", "p"."category", SUM("o"."amount") '
            'FROM "public"."orders" o '
            'JOIN "public"."customers" c ON "o"."customer_id" = "c"."customer_id" '
            'JOIN "public"."products" p ON "o"."customer_id" = "p"."product_id" '
            'GROUP BY "c"."country", "p"."category"'
        ),
        required_relationships=_generic_order_dimension_relationships(),
    )

    violation = next(
        check for check in checks
        if check["code"] == "relationship_violation"
    )
    assert violation["status"] == "failed"


def test_correctness_allows_metric_on_many_side_joining_one_side():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Sales.SalesOrderDetail"],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
        sql='SELECT "p"."Name", SUM("d"."LineTotal") FROM "Sales"."SalesOrderDetail" d JOIN "Production"."Product" p ON "d"."ProductID" = "p"."ProductID" GROUP BY "p"."Name"',
        governed_metrics=[{"name": "Revenue", "entity_id": 20, "aggregation": "sum"}],
        required_relationships=_product_line_relationship(),
    )
    assert any(item["code"] == "join_fanout_alignment" for item in checks)
    assert not any(item["code"] == "join_fanout_violation" for item in checks)


def test_correctness_rejects_sum_metric_on_one_side_joining_many_side():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Sales.SalesOrderDetail"],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
        sql='SELECT SUM("p"."ListPrice") FROM "Production"."Product" p JOIN "Sales"."SalesOrderDetail" d ON "p"."ProductID" = "d"."ProductID"',
        governed_metrics=[{"name": "Catalog Value", "entity_id": 10, "aggregation": "sum"}],
        required_relationships=_product_line_relationship(),
    )
    violation = next(item for item in checks if item["code"] == "join_fanout_violation")
    assert violation["status"] == "failed"
    assert violation["metric"] == "Catalog Value"


def test_correctness_allows_count_distinct_on_one_side_across_many_join():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Sales.SalesOrderDetail"],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
        sql='SELECT COUNT(DISTINCT "p"."ProductID") FROM "Production"."Product" p JOIN "Sales"."SalesOrderDetail" d ON "p"."ProductID" = "d"."ProductID"',
        governed_metrics=[{"name": "Product Count", "entity_id": 10, "aggregation": "count_distinct"}],
        required_relationships=_product_line_relationship(),
    )
    assert any(item["code"] == "join_fanout_alignment" for item in checks)


def test_correctness_rejects_fanout_even_with_unrelated_scalar_subquery():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Sales.SalesOrderDetail"],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
        sql=(
            'SELECT SUM("p"."ListPrice"), (SELECT 1) AS marker '
            'FROM "Production"."Product" p '
            'JOIN "Sales"."SalesOrderDetail" d ON "p"."ProductID" = "d"."ProductID"'
        ),
        governed_metrics=[{"name": "Catalog Value", "entity_id": 10, "aggregation": "sum"}],
        required_relationships=_product_line_relationship(),
    )
    assert any(item["code"] == "join_fanout_violation" for item in checks)
    assert not any(item["code"] == "fanout_verification_unavailable" for item in checks)


def test_correctness_skips_fanout_judgement_for_preaggregated_subquery():
    checks = assess_query_correctness(
        affected_tables=["Production.Product", "Sales.SalesOrderDetail"],
        governed_tables=["Production.Product", "Sales.SalesOrderDetail"],
        sql='SELECT SUM(x.total) FROM (SELECT "p"."ProductID", MAX("p"."ListPrice") AS total FROM "Production"."Product" p JOIN "Sales"."SalesOrderDetail" d ON "p"."ProductID" = "d"."ProductID" GROUP BY "p"."ProductID") x',
        governed_metrics=[{"name": "Catalog Value", "entity_id": 10, "aggregation": "sum"}],
        required_relationships=_product_line_relationship(),
    )
    assert any(item["code"] == "fanout_safety_evidence_incomplete" for item in checks)
    assert any(item["code"] == "join_fanout_violation" and item["status"] == "failed" for item in checks)



def _monthly_time_plan():
    return {
        "status": "resolved",
        "column_name": "OrderDate",
        "start": "2026-01-01",
        "end_exclusive": "2027-01-01",
        "grouping_grain": "month",
        "comparison": False,
    }


def test_correctness_passes_governed_time_range_and_month_grain():
    checks = assess_query_correctness(
        affected_tables=["Sales.SalesOrderHeader"],
        governed_tables=["Sales.SalesOrderHeader"],
        sql="""SELECT DATE_TRUNC('month', "OrderDate"), COUNT(*) FROM "Sales"."SalesOrderHeader"
               WHERE "OrderDate" >= DATE '2026-01-01' AND "OrderDate" < DATE '2027-01-01'
               GROUP BY DATE_TRUNC('month', "OrderDate")""",
        required_time_plan=_monthly_time_plan(),
    )
    assert any(item["code"] == "time_filter_alignment" for item in checks)
    assert any(item["code"] == "time_grain_alignment" for item in checks)


def test_correctness_rejects_wrong_time_column_for_resolved_range():
    checks = assess_query_correctness(
        affected_tables=["Sales.SalesOrderHeader"],
        governed_tables=["Sales.SalesOrderHeader"],
        sql="""SELECT COUNT(*) FROM "Sales"."SalesOrderHeader"
               WHERE "ShipDate" >= DATE '2026-01-01' AND "ShipDate" < DATE '2027-01-01'""",
        required_time_plan={**_monthly_time_plan(), "grouping_grain": None},
    )
    violation = next(item for item in checks if item["code"] == "time_filter_violation")
    assert violation["status"] == "failed"


def test_correctness_rejects_wrong_time_range_boundary():
    checks = assess_query_correctness(
        affected_tables=["Sales.SalesOrderHeader"],
        governed_tables=["Sales.SalesOrderHeader"],
        sql="""SELECT COUNT(*) FROM "Sales"."SalesOrderHeader"
               WHERE "OrderDate" >= DATE '2026-02-01' AND "OrderDate" < DATE '2027-01-01'""",
        required_time_plan={**_monthly_time_plan(), "grouping_grain": None},
    )
    violation = next(item for item in checks if item["code"] == "time_filter_violation")
    assert violation["missing_lower_bound"] is True


def test_correctness_rejects_wrong_time_grouping_grain():
    checks = assess_query_correctness(
        affected_tables=["Sales.SalesOrderHeader"],
        governed_tables=["Sales.SalesOrderHeader"],
        sql="""SELECT DATE_TRUNC('year', "OrderDate"), COUNT(*) FROM "Sales"."SalesOrderHeader"
               WHERE "OrderDate" >= DATE '2026-01-01' AND "OrderDate" < DATE '2027-01-01'
               GROUP BY DATE_TRUNC('year', "OrderDate")""",
        required_time_plan=_monthly_time_plan(),
    )
    assert any(item["code"] == "time_grain_violation" for item in checks)


def test_correctness_accepts_grouping_only_time_plan():
    checks = assess_query_correctness(
        affected_tables=["Sales.SalesOrderHeader"],
        governed_tables=["Sales.SalesOrderHeader"],
        sql="""SELECT DATE_TRUNC('quarter', "OrderDate"), COUNT(*) FROM "Sales"."SalesOrderHeader"
               GROUP BY DATE_TRUNC('quarter', "OrderDate")""",
        required_time_plan={
            "status": "resolved",
            "column_name": "OrderDate",
            "grouping_grain": "quarter",
            "comparison": False,
        },
    )
    assert any(item["code"] == "time_grain_alignment" for item in checks)
    assert not any(item["code"] == "time_filter_violation" for item in checks)


def test_correctness_accepts_comparison_envelope_range():
    checks = assess_query_correctness(
        affected_tables=["Sales.SalesOrderHeader"],
        governed_tables=["Sales.SalesOrderHeader"],
        sql="""SELECT DATE_TRUNC('month', "OrderDate"), COUNT(*) FROM "Sales"."SalesOrderHeader"
               WHERE "OrderDate" >= DATE '2026-09-01' AND "OrderDate" < DATE '2026-11-01'
               GROUP BY DATE_TRUNC('month', "OrderDate")""",
        required_time_plan={
            "status": "resolved",
            "column_name": "OrderDate",
            "grouping_grain": "month",
            "comparison": True,
            "periods": [
                {"label": "this month", "start": "2026-10-01", "end_exclusive": "2026-11-01"},
                {"label": "last month", "start": "2026-09-01", "end_exclusive": "2026-10-01"},
            ],
        },
    )
    assert any(item["code"] == "time_filter_alignment" for item in checks)
    assert any(item["code"] == "time_grain_alignment" for item in checks)




def test_correctness_accepts_comparison_with_all_governed_period_boundaries():
    plan = {
        "status": "resolved",
        "column_name": "OrderDate",
        "grouping_grain": None,
        "comparison": True,
        "periods": [
            {"label": "this month", "start": "2026-10-01", "end_exclusive": "2026-11-01"},
            {"label": "last month", "start": "2026-09-01", "end_exclusive": "2026-10-01"},
        ],
    }
    checks = assess_query_correctness(
        affected_tables=["Sales.SalesOrderHeader"],
        governed_tables=["Sales.SalesOrderHeader"],
        sql="""SELECT
                 SUM(CASE WHEN "OrderDate" >= DATE '2026-10-01' AND "OrderDate" < DATE '2026-11-01' THEN 1 ELSE 0 END),
                 SUM(CASE WHEN "OrderDate" >= DATE '2026-09-01' AND "OrderDate" < DATE '2026-10-01' THEN 1 ELSE 0 END)
               FROM "Sales"."SalesOrderHeader"
               WHERE "OrderDate" >= DATE '2026-09-01' AND "OrderDate" < DATE '2026-11-01'""",
        required_time_plan=plan,
    )

    assert any(item["code"] == "time_filter_alignment" for item in checks)
    assert any(item["code"] == "time_comparison_alignment" for item in checks)
    assert not any(item["code"] == "time_comparison_violation" for item in checks)


def test_correctness_rejects_comparison_envelope_without_period_split():
    plan = {
        "status": "resolved",
        "column_name": "OrderDate",
        "grouping_grain": None,
        "comparison": True,
        "periods": [
            {"label": "this month", "start": "2026-10-01", "end_exclusive": "2026-11-01"},
            {"label": "last month", "start": "2026-09-01", "end_exclusive": "2026-10-01"},
        ],
    }
    checks = assess_query_correctness(
        affected_tables=["Sales.SalesOrderHeader"],
        governed_tables=["Sales.SalesOrderHeader"],
        sql="""SELECT COUNT(*) FROM "Sales"."SalesOrderHeader"
               WHERE "OrderDate" >= DATE '2026-09-01' AND "OrderDate" < DATE '2026-11-01'""",
        required_time_plan=plan,
    )

    assert any(item["code"] == "time_filter_alignment" for item in checks)
    violation = next(item for item in checks if item["code"] == "time_comparison_violation")
    assert violation["status"] == "failed"
    assert violation["missing_period_boundaries"] == ["2026-10-01"]


def test_correctness_honors_non_postgresql_dialect_for_scope_and_parsing():
    checks = assess_query_correctness(
        affected_tables=["analytics.orders"],
        governed_tables=["analytics.orders"],
        sql="SELECT `customer_id`, SUM(`amount`) FROM `analytics`.`orders` GROUP BY `customer_id`",
        required_grouping_columns=["customer_id"],
        dialect="mysql",
    )

    assert any(item["code"] == "grouping_dimension_alignment" for item in checks)
    assert any(item["code"] == "physical_scope_alignment" for item in checks)
    assert not any(
        item["code"] == "grouping_verification_unavailable"
        for item in checks
    )


def test_correctness_honors_non_postgresql_dialect_for_metric_expression():
    checks = assess_query_correctness(
        affected_tables=["analytics.orders"],
        governed_tables=["analytics.orders"],
        sql="SELECT SUM(`quantity` * `unit_price`) AS `revenue` FROM `analytics`.`orders`",
        governed_metrics=[{
            "name": "Revenue",
            "aggregation": "sum",
            "calculation_expression": "`quantity` * `unit_price`",
        }],
        dialect="mysql",
    )

    assert any(item["code"] == "metric_expression_alignment" for item in checks)
    assert not any(
        item["code"] == "metric_expression_verification_unavailable"
        for item in checks
    )


def test_comparison_rejects_collapsed_filtered_cohorts():
    checks = assess_query_correctness(
        affected_tables=["astra.vessels"],
        governed_tables=["astra.vessels"],
        question="Compare new building vessel counts between MSC and Maersk in all segments",
        sql=(
            "SELECT vessel_segment, COUNT(DISTINCT id) FROM astra.vessels "
            "WHERE operator IN ('MSC', 'Maersk') AND vessel_status = 'ON ORDER' "
            "GROUP BY vessel_segment"
        ),
    )
    violation = next(check for check in checks if check["code"] == "comparison_dimension_violation")
    assert violation["status"] == "failed"
    assert violation["missing_columns"] == ["operator"]


def test_comparison_accepts_separate_filtered_cohorts():
    checks = assess_query_correctness(
        affected_tables=["astra.vessels"],
        governed_tables=["astra.vessels"],
        question="Compare new building vessel counts between MSC and Maersk in all segments",
        sql=(
            "SELECT vessel_segment, operator, COUNT(DISTINCT id) FROM astra.vessels "
            "WHERE operator IN ('MSC', 'Maersk') AND vessel_status = 'ON ORDER' "
            "GROUP BY vessel_segment, operator"
        ),
    )
    assert any(check["code"] == "comparison_dimension_alignment" and check["status"] == "passed"
               for check in checks)


def test_non_comparison_can_aggregate_filtered_cohorts_together():
    checks = assess_query_correctness(
        affected_tables=["astra.vessels"],
        governed_tables=["astra.vessels"],
        question="How many vessels belong to MSC and Maersk combined by segment?",
        sql=(
            "SELECT vessel_segment, COUNT(*) FROM astra.vessels "
            "WHERE operator IN ('MSC', 'Maersk') GROUP BY vessel_segment"
        ),
    )
    assert not any(check["code"].startswith("comparison_dimension_") for check in checks)


@pytest.mark.parametrize("sql,expected", [
    ("SELECT segment, COUNT(*) FROM assets WHERE operator IN ('MSC', 'Maersk') GROUP BY segment", "comparison_dimension_violation"),
    ("SELECT segment, operator, COUNT(*) FROM assets WHERE operator IN ('MSC', 'Maersk') GROUP BY segment, operator", "comparison_dimension_alignment"),
    ("SELECT segment, COUNT(*) FROM assets WHERE customer IN ('Alpha', 'Beta') GROUP BY segment", "comparison_dimension_violation"),
    ("SELECT segment, customer, SUM(amount) FROM assets WHERE customer IN ('Alpha', 'Beta') GROUP BY segment, customer", "comparison_dimension_alignment"),
])
def test_and_joined_named_cohorts_require_grouping(sql, expected):
    from datapilot.application.services.query_correctness import assess_query_correctness
    question = "Show values for MSC and Maersk" if "MSC" in sql else "Show values for Alpha and Beta"
    checks = assess_query_correctness(
        affected_tables=["assets"], governed_tables=["assets"],
        sql=sql, question=question,
    )
    assert expected in {check["code"] for check in checks}


def test_combined_total_without_group_by_not_falsely_rejected():
    from datapilot.application.services.query_correctness import assess_query_correctness
    checks = assess_query_correctness(
        affected_tables=["assets"], governed_tables=["assets"],
        sql="SELECT COUNT(*) FROM assets WHERE operator IN ('MSC', 'Maersk')",
        question="Show combined total for MSC and Maersk",
    )
    assert not any(check["code"] == "comparison_dimension_violation" for check in checks)


@pytest.mark.parametrize("combined_wording", [
    "MSC and Maersk combined by segment",
    "MSC and Maersk together by segment",
    "MSC and Maersk collectively by segment",
    "MSC and Maersk in total by segment",
])
def test_explicit_combined_cohorts_are_not_separate_comparisons(combined_wording):
    checks = assess_query_correctness(
        affected_tables=["astra.vessels"],
        governed_tables=["astra.vessels"],
        question="Show vessel counts for " + combined_wording,
        sql=(
            "SELECT vessel_segment, COUNT(*) FROM astra.vessels "
            "WHERE operator IN ('MSC', 'Maersk') GROUP BY vessel_segment"
        ),
    )
    assert not any(check["code"].startswith("comparison_dimension_") for check in checks)


@pytest.mark.parametrize("attribute,values,question", [
    ("operator", ("maersk", "msc"), "Show segment wise counts for Maersk and MSC"),
    ("customer", ("alpha", "beta"), "Show region wise sales for Alpha and Beta"),
    ("supplier", ("north", "south"), "Show product wise totals for North and South"),
])
def test_casefolded_named_cohorts_cannot_be_merged(attribute, values, question):
    predicate = f"LOWER({attribute}) IN ('{values[0]}', '{values[1]}')"
    sql = f"SELECT segment, COUNT(DISTINCT id) FROM items WHERE {predicate} GROUP BY segment"
    checks = assess_query_correctness(
        affected_tables=["items"], governed_tables=["items"],
        sql=sql, question=question,
    )
    assert any(c["code"] == "comparison_dimension_violation" and c["status"] == "failed" for c in checks)
    aligned = sql.replace("GROUP BY segment", f"GROUP BY segment, {attribute}")
    checks = assess_query_correctness(
        affected_tables=["items"], governed_tables=["items"],
        sql=aligned, question=question,
    )
    assert any(c["code"] == "comparison_dimension_alignment" and c["status"] == "passed" for c in checks)


def test_explicit_combined_casefolded_cohorts_may_be_aggregated():
    checks = assess_query_correctness(
        affected_tables=["items"], governed_tables=["items"],
        sql="SELECT segment, COUNT(*) FROM items WHERE LOWER(operator) IN ('msc', 'maersk') GROUP BY segment",
        question="Show MSC and Maersk combined by segment",
    )
    assert not any(c["code"] == "comparison_dimension_violation" for c in checks)


def test_cte_alias_does_not_count_as_unauthorized_physical_table():
    from datapilot.application.services.query_correctness import assess_query_correctness
    sql = "WITH vessel_counts AS (SELECT operator, COUNT(*) AS n FROM astra.vessels GROUP BY operator) SELECT * FROM vessel_counts"
    checks = assess_query_correctness(
        affected_tables=["vessel_counts", "astra.vessels"],
        governed_tables=["astra.vessels"],
        sql=sql,
    )
    assert not any(c["code"] == "physical_scope_violation" for c in checks)


def test_cte_cannot_hide_unauthorized_physical_table():
    from datapilot.application.services.query_correctness import assess_query_correctness
    sql = "WITH vessel_counts AS (SELECT * FROM private.secret) SELECT * FROM vessel_counts"
    checks = assess_query_correctness(
        affected_tables=["vessel_counts"],
        governed_tables=["astra.vessels"],
        sql=sql,
    )
    assert any(c["code"] == "physical_scope_violation" for c in checks)


def test_governed_array_categorical_membership_accepts_containment():
    from datapilot.application.services.query_correctness import assess_query_correctness
    checks = assess_query_correctness(
        affected_tables=["public.items"], governed_tables=["public.items"],
        sql="SELECT * FROM public.items WHERE tags @> ARRAY['LNG']",
        required_filters=[{"column_name": "tags", "operator": "=", "value": "LNG", "data_type": "text[]"}],
    )
    assert any(c["code"] == "filter_alignment" for c in checks)


def test_governed_array_categorical_membership_rejects_unrelated_literal():
    from datapilot.application.services.query_correctness import assess_query_correctness
    checks = assess_query_correctness(
        affected_tables=["public.items"], governed_tables=["public.items"],
        sql="SELECT * FROM public.items WHERE name = 'LNG'",
        required_filters=[{"column_name": "tags", "operator": "=", "value": "LNG", "data_type": "text[]"}],
    )
    assert any(c["code"] == "filter_violation" for c in checks)


def test_explicit_grouping_allows_additional_dimension_named_in_question():
    from datapilot.application.services.query_correctness import assess_query_correctness
    checks = assess_query_correctness(
        affected_tables=["public.items"], governed_tables=["public.items"],
        sql="SELECT operator, ownership_status, COUNT(*) FROM public.items GROUP BY operator, ownership_status",
        question="Compare vessel counts for each operator, grouped by ownership status",
        required_grouping_columns=["ownership_status"],
    )
    assert not any(c["code"] == "explicit_grouping_grain_violation" for c in checks)


def test_array_expansion_rejects_unnest_directly_in_group_by():
    from datapilot.application.services.query_correctness import assess_query_correctness

    checks = assess_query_correctness(
        affected_tables=["public.assets"],
        governed_tables=["public.assets"],
        sql="SELECT UNNEST(tags), COUNT(*) FROM public.assets GROUP BY UNNEST(tags)",
    )
    assert any(
        check["code"] == "array_expansion_grouping_violation"
        and check["status"] == "failed"
        for check in checks
    )


def test_array_expansion_allows_lateral_unnest_grouped_by_element():
    from datapilot.application.services.query_correctness import assess_query_correctness

    checks = assess_query_correctness(
        affected_tables=["public.assets"],
        governed_tables=["public.assets"],
        sql=(
            "SELECT fuel.value, COUNT(*) FROM public.assets AS a "
            "CROSS JOIN LATERAL UNNEST(a.tags) AS fuel(value) "
            "GROUP BY fuel.value"
        ),
    )
    assert not any(
        check["code"] == "array_expansion_grouping_violation"
        and check["status"] == "failed"
        for check in checks
    )


def test_evaluation_replay_uses_stored_responses_without_api_calls(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    cases = tmp_path / "cases.json"
    previous = tmp_path / "previous.json"
    output = tmp_path / "replayed.json"
    cases.write_text(json.dumps([
        {"id": "A", "question": "Count records",
         "expect": {"sql_contains": ["COUNT(*)"]}},
        {"id": "B", "question": "Show records",
         "expect": {"sql_contains": ["FROM public.records"]}},
    ]), encoding="utf-8")
    previous.write_text(json.dumps({"results": [
        {"id": "A", "response": {"status": "completed",
                                "sql": "SELECT COUNT(*) FROM public.records"}},
        {"id": "B", "response": {"status": "completed",
                                "sql": "SELECT * FROM public.records"}},
    ]}), encoding="utf-8")
    root = Path(__file__).resolve().parents[4]
    completed = subprocess.run([
        sys.executable, str(root / "scripts" / "run_nl2sql_evaluation.py"),
        "--cases", str(cases), "--source", "offline",
        "--base-url", "http://127.0.0.1:1",
        "--replay", str(previous), "--output", str(output),
    ], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["mode"] == "replay"
    assert report["summary"]["pass"] == 2


@pytest.mark.parametrize("sql,expected", [
    ("SELECT a.id FROM public.orders AS a", []),
    ("SELECT x.id FROM (SELECT a.id FROM public.orders AS a) AS x", []),
    ("SELECT a.id FROM (SELECT a.id FROM public.orders AS a) AS x", ["a"]),
    ("WITH totals AS (SELECT a.id FROM public.orders AS a) SELECT t.id FROM totals AS t", []),
    ("WITH totals AS (SELECT a.id FROM public.orders AS a) SELECT a.id FROM totals AS t", ["a"]),
    ("SELECT c.id FROM public.customers AS c WHERE EXISTS (SELECT 1 FROM public.orders AS o WHERE o.customer_id = c.id)", []),
    ("SELECT c.id FROM public.customers AS c WHERE EXISTS (SELECT 1 FROM public.orders AS o WHERE z.customer_id = c.id)", ["z"]),
])
def test_lexical_qualifier_validation(sql, expected):
    import sqlglot
    from datapilot.application.services.query_orchestrator import _invalid_qualified_columns
    ast = sqlglot.parse_one(sql, read="postgres")
    assert sorted({col.table for col in _invalid_qualified_columns(ast)}) == expected


@pytest.mark.parametrize("sql,expected", [
    ("WITH x AS (SELECT a.id FROM public.orders a) SELECT x.id FROM x", []),
    ("WITH x AS (SELECT a.id FROM public.orders a) SELECT z.id FROM x", ["z"]),
    ("SELECT q.id FROM (SELECT a.id FROM public.orders a) q", []),
    ("SELECT a.id FROM public.orders a WHERE EXISTS (SELECT 1 FROM public.customers c WHERE c.id = a.customer_id)", []),
    ("SELECT a.id FROM public.orders a WHERE EXISTS (SELECT 1 FROM public.customers c WHERE missing.id = a.customer_id)", ["missing"]),
    ("SELECT a.id FROM public.orders a JOIN public.customers c ON c.id = a.customer_id", []),
    ("SELECT a.id FROM public.orders a JOIN public.customers c ON absent.id = a.customer_id", ["absent"]),
])
def test_scope_qualifiers_across_ctes_joins_and_correlations(sql, expected):
    import sqlglot
    from datapilot.application.services.query_orchestrator import _invalid_qualified_columns
    parsed = sqlglot.parse_one(sql, read="postgres")
    actual = sorted({col.table for col in _invalid_qualified_columns(parsed)})
    assert actual == expected
