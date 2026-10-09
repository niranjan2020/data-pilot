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


def test_comparison_accepts_simple_inflected_user_expression():
    sql = "SELECT ownership_status, count(*) FROM assets GROUP BY ownership_status"
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Show own versus chartered assets", sql, ENTITIES
        )


def test_comparison_rejects_one_sided_filter():
    sql = "SELECT ownership_status, count(*) FROM assets WHERE ownership_status = 'O' GROUP BY ownership_status"
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES
        )


def test_repair_missing_categorical_filter_preserves_existing_predicates():
    sql = "SELECT ownership_status, COUNT(*) FROM assets WHERE active = TRUE GROUP BY ownership_status"
    with pytest.raises(SQLValidationError) as captured:
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES
        )
    repaired = QueryOrchestrator._repair_explicit_categorical_comparison(sql, captured.value)
    assert repaired is not None
    assert "active = TRUE" in repaired
    assert "'O'" in repaired and "'T'" in repaired
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Compare owned versus chartered assets", repaired, ENTITIES
    )


def test_repair_refuses_existing_one_sided_filter():
    sql = "SELECT ownership_status, COUNT(*) FROM assets WHERE ownership_status = 'O' GROUP BY ownership_status"
    with pytest.raises(SQLValidationError) as captured:
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES
        )
    assert QueryOrchestrator._repair_explicit_categorical_comparison(sql, captured.value) is None


def test_repair_refuses_joined_queries():
    sql = "SELECT a.ownership_status, COUNT(*) FROM assets a JOIN owners b ON a.id = b.asset_id GROUP BY a.ownership_status"
    with pytest.raises(SQLValidationError) as captured:
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES
        )
    assert QueryOrchestrator._repair_explicit_categorical_comparison(sql, captured.value) is None


@pytest.mark.parametrize("sql", [
    "SELECT ownership_status, count(*) FROM assets WHERE ownership_status = 'O' OR ownership_status = 'T' GROUP BY ownership_status",
    "SELECT ownership_status, count(*) FROM assets WHERE NOT ownership_status IN ('O', 'T') GROUP BY ownership_status",
    "SELECT ownership_status, count(*) FROM assets WHERE active = TRUE GROUP BY ownership_status HAVING MAX(ownership_status) IN ('O', 'T')",
    "SELECT ownership_status, count(*) FROM assets WHERE other_status IN ('O', 'T') GROUP BY ownership_status",
    "SELECT ownership_status, count(*) FROM assets WHERE ownership_status IN ('O', 'T') OR active = TRUE GROUP BY ownership_status",
])
def test_comparison_does_not_accept_non_guaranteed_filter(sql):
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES
        )


def test_comparison_accepts_positive_filter_with_other_conditions():
    sql = (
        "SELECT ownership_status, count(*) FROM assets "
        "WHERE active = TRUE AND ownership_status IN ('O', 'T') "
        "GROUP BY ownership_status"
    )
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Compare owned versus chartered assets", sql, ENTITIES
    )


def test_comparison_rejects_contradictory_and_values():
    sql = (
        "SELECT ownership_status, COUNT(*) FROM assets "
        "WHERE ownership_status = 'O' AND ownership_status = 'T' "
        "GROUP BY ownership_status"
    )
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES
        )


def test_comparison_rejects_separate_in_predicates_with_disjoint_values():
    sql = (
        "SELECT ownership_status, COUNT(*) FROM assets "
        "WHERE ownership_status IN ('O') AND ownership_status IN ('T') "
        "GROUP BY ownership_status"
    )
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES
        )


@pytest.mark.parametrize("extra", [
    "ownership_status = 'O'",
    "ownership_status NOT IN ('T')",
    "ownership_status <> 'T'",
    "(ownership_status = 'O' OR active = TRUE)",
])
def test_comparison_rejects_additional_restrictive_category_predicate(extra):
    sql = (
        "SELECT ownership_status, COUNT(*) FROM assets "
        "WHERE ownership_status IN ('O', 'T') AND " + extra +
        " GROUP BY ownership_status"
    )
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES
        )


def test_comparison_accepts_valid_single_table_alias():
    sql = (
        "SELECT a.ownership_status, COUNT(*) FROM assets AS a "
        "WHERE a.ownership_status IN ('O', 'T') GROUP BY a.ownership_status"
    )
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Compare owned versus chartered assets", sql, ENTITIES
    )


def test_comparison_rejects_unknown_table_alias():
    sql = (
        "SELECT a.ownership_status, COUNT(*) FROM assets AS a "
        "WHERE x.ownership_status IN ('O', 'T') GROUP BY a.ownership_status"
    )
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES
        )


def test_comparison_rejects_ambiguous_unqualified_join_filter():
    sql = (
        "SELECT a.ownership_status, COUNT(*) FROM assets AS a "
        "JOIN other_assets AS b ON b.id = a.id "
        "WHERE ownership_status IN ('O', 'T') GROUP BY a.ownership_status"
    )
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, ENTITIES
        )
