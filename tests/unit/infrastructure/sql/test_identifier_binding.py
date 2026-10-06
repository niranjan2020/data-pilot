"""Tests for physical SQL identifier binding."""

from datapilot.domain.models import ColumnMetadata, SchemaMetadata, TableMetadata
from datapilot.infrastructure.sql.identifier_binding import SQLGlotIdentifierBinder, bind_physical_identifiers


def _schema() -> SchemaMetadata:
    return SchemaMetadata(
        dialect="postgresql",
        tables=[
            TableMetadata(
                schema_name="Production",
                name="Product",
                columns=[
                    ColumnMetadata(name="ProductID", data_type="integer"),
                    ColumnMetadata(name="Name", data_type="text"),
                    ColumnMetadata(name="Color", data_type="text"),
                ],
            ),
            TableMetadata(
                schema_name="Sales",
                name="SalesOrderHeader",
                columns=[
                    ColumnMetadata(name="SalesOrderID", data_type="integer"),
                    ColumnMetadata(name="TotalDue", data_type="numeric"),
                ],
            ),
        ],
    )


def test_binds_unaliased_mixed_case_table_qualifier() -> None:
    sql = "SELECT Product.ProductID FROM Production.Product WHERE Product.Color = 'Red'"

    bound = bind_physical_identifiers(sql, _schema(), "postgresql")

    assert 'SELECT "ProductID" FROM "Production"."Product"' in bound
    assert '"Color" = \'Red\'' in bound
    assert '"Product"."ProductID"' not in bound


def test_preserves_query_alias_while_binding_column_case() -> None:
    sql = "SELECT t1.productid FROM Production.Product AS t1 WHERE t1.color = 'Red'"

    bound = bind_physical_identifiers(sql, _schema(), "postgresql")

    assert '"t1"."ProductID"' in bound
    assert '"t1"."Color"' in bound
    assert 'AS "t1"' in bound


def test_binds_other_unaliased_physical_table_qualifiers() -> None:
    sql = "SELECT SalesOrderHeader.SalesOrderID FROM Sales.SalesOrderHeader"

    bound = bind_physical_identifiers(sql, _schema(), "postgresql")

    assert bound == 'SELECT "SalesOrderID" FROM "Sales"."SalesOrderHeader"'


def test_binds_unqualified_columns_against_referenced_table_only() -> None:
    sql = "SELECT productid, name FROM Production.Product WHERE color = 'Red'"

    bound = bind_physical_identifiers(sql, _schema(), "postgresql")

    assert 'SELECT "ProductID", "Name" FROM "Production"."Product"' in bound
    assert '"Color" = \'Red\'' in bound


def test_binds_alias_qualified_mixed_case_columns() -> None:
    sql = (
        "SELECT SUM(T1.OrderQty) FROM Sales.SalesOrderDetail AS T1 "
        "JOIN Production.Product AS T2 ON T1.ProductID = T2.ProductID "
        "WHERE T2.Color = 'Red'"
    )

    bound = bind_physical_identifiers(sql, _schema_with_sales_detail(), "postgresql")

    assert '"T1"."OrderQty"' in bound
    assert '"T1"."ProductID" = "T2"."ProductID"' in bound
    assert '"T2"."Color" = \'Red\'' in bound


def _schema_with_sales_detail() -> SchemaMetadata:
    schema = _schema()
    schema.tables.append(
        TableMetadata(
            schema_name="Sales",
            name="SalesOrderDetail",
            columns=[
                ColumnMetadata(name="SalesOrderDetailID", data_type="integer"),
                ColumnMetadata(name="ProductID", data_type="integer"),
                ColumnMetadata(name="OrderQty", data_type="integer"),
            ],
        )
    )
    return schema


def test_removes_schema_name_used_as_column_qualifier() -> None:
    sql = 'SELECT AVG(Sales."TotalDue") FROM "Sales"."SalesOrderHeader"'

    bound = bind_physical_identifiers(sql, _schema(), "postgresql")

    assert bound == 'SELECT AVG("TotalDue") FROM "Sales"."SalesOrderHeader"'


def test_sqlglot_binder_adapter_preserves_existing_binding_behavior() -> None:
    binder = SQLGlotIdentifierBinder()

    bound = binder.bind(
        "SELECT productid FROM Production.Product",
        _schema(),
        "postgresql",
    )

    assert bound == 'SELECT "ProductID" FROM "Production"."Product"'
