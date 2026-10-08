"""C4 discovery contract for physical uniqueness evidence."""

from datapilot.domain.models import SchemaMetadata, TableMetadata, UniqueConstraintMetadata


def test_composite_unique_constraint_round_trip():
    schema = SchemaMetadata(
        schema_name="sales",
        tables=[
            TableMetadata(
                name="orders",
                schema_name="sales",
                primary_keys=["id"],
                unique_constraints=[
                    UniqueConstraintMetadata(name="orders_pkey", columns=["id"], is_primary_key=True),
                    UniqueConstraintMetadata(name="orders_tenant_code_key", columns=["tenant_id", "code"]),
                ],
            )
        ],
    )
    restored = SchemaMetadata.model_validate_json(schema.model_dump_json())
    constraints = restored.tables[0].unique_constraints
    assert [(c.name, c.columns, c.is_primary_key) for c in constraints] == [
        ("orders_pkey", ["id"], True),
        ("orders_tenant_code_key", ["tenant_id", "code"], False),
    ]


def test_legacy_schema_without_unique_constraints_remains_readable():
    legacy = {"tables": [{"name": "vessels", "schema_name": "astra"}]}
    restored = SchemaMetadata.model_validate(legacy)
    assert restored.tables[0].unique_constraints == []
