"""Architecture regressions for Stage B dialect/provider isolation."""

from __future__ import annotations

from pathlib import Path

from datapilot.infrastructure.sql.dialects import sqlglot_dialect


ROOT = Path(__file__).parents[2]
CORRECTNESS = ROOT / "src" / "datapilot" / "application" / "services" / "query_correctness.py"
ORCHESTRATOR = ROOT / "src" / "datapilot" / "application" / "services" / "query_orchestrator.py"
RECOVERY = ROOT / "src" / "datapilot" / "application" / "services" / "execution_recovery.py"
POSTGRES = ROOT / "src" / "datapilot" / "infrastructure" / "database" / "postgresql.py"


def test_sqlglot_dialect_maps_postgresql_and_preserves_other_dialects() -> None:
    assert sqlglot_dialect("postgresql") == "postgres"
    assert sqlglot_dialect("postgres") == "postgres"
    assert sqlglot_dialect("mysql") == "mysql"


def test_governed_correctness_has_no_hardcoded_postgres_sqlglot_dialect() -> None:
    source = CORRECTNESS.read_text(encoding="utf-8")

    assert 'read="postgres"' not in source
    assert "read='postgres'" not in source
    assert 'dialect="postgres"' not in source
    assert "dialect='postgres'" not in source
    assert "sqlglot_dialect(dialect)" in source


def test_orchestrator_depends_on_sql_binder_port_not_concrete_binding_function() -> None:
    source = ORCHESTRATOR.read_text(encoding="utf-8")

    assert "SQLIdentifierBinder" in source
    assert "bind_physical_identifiers" not in source
    assert "self._sql_identifier_binder.bind(" in source


def test_application_recovery_policy_contains_no_postgresql_sqlstate_table() -> None:
    source = RECOVERY.read_text(encoding="utf-8")

    for sqlstate in ("42703", "42P01", "42501", "57014", "08006"):
        assert sqlstate not in source
    assert "ExecutionRecoveryEvidence" in source


def test_postgresql_adapter_owns_postgresql_recovery_codes() -> None:
    source = POSTGRES.read_text(encoding="utf-8")

    for sqlstate in ("42703", "42P01", "42501", "57014"):
        assert sqlstate in source
    assert "_classify_postgres_execution_error" in source
