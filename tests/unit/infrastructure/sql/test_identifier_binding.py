"""Tests for physical SQL identifier binding."""

from datapilot.domain.models import ColumnMetadata, SchemaMetadata, TableMetadata
from datapilot.infrastructure.sql.identifier_binding import bind_physical_identifiers


def _schema() -> SchemaMetadata:
    return SchemaMetadata(
        dialect="postgresql",
        tables=[
            TableMetadata(
                schema_name="Production",
                name="Product",
                columns=[
                    ColumnMetadata(name="ProductID", data_type="integer"),
                    ColumnMetadata(name="Color", data_type="text"),
                ],
            ),
            TableMetadata(
                schema_name="Sales",
                name="SalesOrderHeader",
                columns=[ColumnMetadata(name="SalesOrderID", data_type="integer")],
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

    assert 't1."ProductID"' in bound
    assert 't1."Color"' in bound
    assert '"t1"' not in bound


def test_binds_other_unaliased_physical_table_qualifiers() -> None:
    sql = "SELECT SalesOrderHeader.SalesOrderID FROM Sales.SalesOrderHeader"

    bound = bind_physical_identifiers(sql, _schema(), "postgresql")

    assert bound == 'SELECT "SalesOrderID" FROM "Sales"."SalesOrderHeader"'


def test_binds_unqualified_columns_against_referenced_table_only() -> None:
    sql = "SELECT productid, name FROM Production.Product WHERE color = 'Red'"

    bound = bind_physical_identifiers(sql, _schema(), "postgresql")

    assert 'SELECT "ProductID", "Name" FROM "Production"."Product"' in bound
    assert '"Color" = \'Red\'' in bound
