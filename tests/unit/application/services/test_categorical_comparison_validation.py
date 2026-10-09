import pytest

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.core.exceptions import SQLValidationError


ENTITIES = [{"name": "Assets", "attributes": [{"column_name": "ownership_status", "value_mappings": [
    {"canonical_value": "O", "synonyms": ["owned"]},
    {"canonical_value": "T", "synonyms": ["chartered"]},
    {"canonical_value": "TO", "synonyms": ["owned but chartered"]},
]}]}]


def test_explicit_comparison_requires_both_values_in_filter():
    sql = "SELECT ownership_status, count(*) FROM assets GROUP BY ownership_status"
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES
        )


def test_explicit_comparison_accepts_both_values():
    sql = "SELECT ownership_status, count(*) FROM assets WHERE ownership_status IN ('O', 'T') GROUP BY ownership_status"
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Compare owned versus chartered assets", sql, ENTITIES
    )


def test_unrelated_question_does_not_invoke_comparison_constraint():
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Count assets by ownership status",
        "SELECT ownership_status, count(*) FROM assets GROUP BY ownership_status",
        ENTITIES,
    )
