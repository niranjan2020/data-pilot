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


GOVERNED_ASSET_ENTITIES = [{
    **ENTITIES[0],
    "schema_name": "public",
    "table_name": "assets",
}]


def test_comparison_accepts_filter_on_governed_join_table():
    sql = (
        "SELECT a.ownership_status, COUNT(*) FROM public.assets AS a "
        "JOIN public.contracts AS c ON c.asset_id = a.id "
        "WHERE a.ownership_status IN ('O', 'T') "
        "GROUP BY a.ownership_status"
    )
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Compare owned versus chartered assets", sql, GOVERNED_ASSET_ENTITIES
    )


def test_comparison_rejects_same_column_on_unrelated_join_table():
    sql = (
        "SELECT a.ownership_status, COUNT(*) FROM public.assets AS a "
        "JOIN public.contracts AS c ON c.asset_id = a.id "
        "WHERE c.ownership_status IN ('O', 'T') "
        "GROUP BY a.ownership_status"
    )
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, GOVERNED_ASSET_ENTITIES
        )


def test_comparison_rejects_wrong_schema_even_with_same_table_name():
    sql = (
        "SELECT a.ownership_status, COUNT(*) FROM archive.assets AS a "
        "WHERE a.ownership_status IN ('O', 'T') GROUP BY a.ownership_status"
    )
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, GOVERNED_ASSET_ENTITIES
        )


@pytest.mark.parametrize("sql", [
    (
        "SELECT a.ownership_status, COUNT(*) FROM public.assets AS a "
        "WHERE EXISTS (SELECT 1 FROM public.contracts AS c "
        "WHERE c.ownership_status IN ('O', 'T')) "
        "GROUP BY a.ownership_status"
    ),
    (
        "WITH filtered AS (SELECT ownership_status FROM public.assets "
        "WHERE ownership_status IN ('O', 'T')) "
        "SELECT ownership_status, COUNT(*) FROM public.assets "
        "GROUP BY ownership_status"
    ),
])
def test_comparison_rejects_category_filter_only_in_nested_scope(sql):
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare owned versus chartered assets", sql, GOVERNED_ASSET_ENTITIES
        )


def test_single_published_category_requires_sql_filter():
    sql = "SELECT ownership_status, COUNT(*) FROM assets GROUP BY ownership_status"
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Show owned assets", sql, ENTITIES
        )


def test_single_published_category_accepts_sql_filter():
    sql = (
        "SELECT ownership_status, COUNT(*) FROM assets "
        "WHERE ownership_status = 'O' GROUP BY ownership_status"
    )
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Show owned assets", sql, ENTITIES
    )


def test_composite_label_requires_its_own_published_code():
    sql = "SELECT ownership_status, COUNT(*) FROM assets GROUP BY ownership_status"
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Show owned but chartered assets", sql, ENTITIES
        )


def test_composite_label_accepts_exact_published_code():
    sql = "SELECT ownership_status, COUNT(*) FROM assets WHERE ownership_status = 'TO' GROUP BY ownership_status"
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Show owned but chartered assets", sql, ENTITIES
    )


def test_ambiguous_published_synonym_fails_closed():
    entities = [{
        "name": "Assets", "attributes": [{
            "column_name": "ownership_status",
            "value_mappings": [
                {"canonical_value": "O", "synonyms": ["leased"]},
                {"canonical_value": "T", "synonyms": ["leased"]},
            ],
        }],
    }]
    with pytest.raises(SQLValidationError) as captured:
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Show leased assets",
            "SELECT ownership_status, COUNT(*) FROM assets WHERE ownership_status = 'O' GROUP BY ownership_status",
            entities,
        )
    assert captured.value.details["checks"][0]["code"] == "categorical_mapping_ambiguity"


def test_single_published_mapping_requires_filter():
    entities = [{
        "name": "Orders",
        "schema_name": "sales",
        "table_name": "orders",
        "attributes": [{
            "column_name": "order_state",
            "value_mappings": [{"canonical_value": "P", "synonyms": ["pending"]}],
        }],
    }]
    sql = "SELECT COUNT(*) FROM sales.orders"
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Count pending orders", sql, entities
        )


def test_single_published_mapping_accepts_correct_filter():
    entities = [{
        "name": "Orders",
        "schema_name": "sales",
        "table_name": "orders",
        "attributes": [{
            "column_name": "order_state",
            "value_mappings": [{"canonical_value": "P", "synonyms": ["pending"]}],
        }],
    }]
    sql = "SELECT COUNT(*) FROM sales.orders WHERE order_state = 'P'"
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Count pending orders", sql, entities
    )


def test_single_category_repair_preserves_existing_filter():
    entities = [{
        "name": "Orders",
        "schema_name": "sales",
        "table_name": "orders",
        "attributes": [{
            "column_name": "order_state",
            "value_mappings": [{"canonical_value": "P", "synonyms": ["pending"]}],
        }],
    }]
    sql = (
        "SELECT order_state, COUNT(*) FROM sales.orders "
        "WHERE active = TRUE GROUP BY order_state"
    )
    with pytest.raises(SQLValidationError) as captured:
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Count pending orders", sql, entities
        )
    repaired = QueryOrchestrator._repair_explicit_categorical_comparison(
        sql, captured.value
    )
    assert repaired is not None
    assert "active = TRUE" in repaired
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Count pending orders", repaired, entities
    )


def test_single_category_repair_does_not_override_existing_constraint():
    entities = [{
        "name": "Orders",
        "attributes": [{
            "column_name": "order_state",
            "value_mappings": [{"canonical_value": "P", "synonyms": ["pending"]}],
        }],
    }]
    sql = (
        "SELECT order_state, COUNT(*) FROM orders "
        "WHERE order_state = 'C' GROUP BY order_state"
    )
    with pytest.raises(SQLValidationError) as captured:
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Count pending orders", sql, entities
        )
    assert QueryOrchestrator._repair_explicit_categorical_comparison(
        sql, captured.value
    ) is None


def test_unrelated_retrieved_entity_does_not_impose_categorical_filter():
    entities = [{
        "name": "Assets", "schema_name": "public", "table_name": "assets",
        "attributes": [{
            "column_name": "ownership_status",
            "value_mappings": [{"canonical_value": "O", "synonyms": ["owned"]}],
        }],
    }]
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Show owned customers",
        "SELECT COUNT(*) FROM public.customers",
        entities,
    )


def test_relevant_entity_still_requires_categorical_filter():
    entities = [{
        "name": "Assets", "schema_name": "public", "table_name": "assets",
        "attributes": [{
            "column_name": "ownership_status",
            "value_mappings": [{"canonical_value": "O", "synonyms": ["owned"]}],
        }],
    }]
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Show owned assets",
            "SELECT COUNT(*) FROM public.assets",
            entities,
        )


def test_same_synonym_on_two_attributes_requires_disambiguation():
    entities = [{
        "name": "Assets", "schema_name": "public", "table_name": "assets",
        "attributes": [
            {"column_name": "ownership_status", "value_mappings": [
                {"canonical_value": "O", "synonyms": ["active"]}]},
            {"column_name": "operating_status", "value_mappings": [
                {"canonical_value": "A", "synonyms": ["active"]}]},
        ],
    }]
    with pytest.raises(SQLValidationError) as captured:
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Count active assets",
            "SELECT COUNT(*) FROM public.assets WHERE ownership_status = 'O'",
            entities,
        )
    assert captured.value.details["checks"][0]["code"] == "categorical_attribute_ambiguity"


def test_distinct_attribute_synonyms_do_not_trigger_attribute_ambiguity():
    entities = [{
        "name": "Assets", "schema_name": "public", "table_name": "assets",
        "attributes": [
            {"column_name": "ownership_status", "value_mappings": [
                {"canonical_value": "O", "synonyms": ["owned"]}]},
            {"column_name": "operating_status", "value_mappings": [
                {"canonical_value": "A", "synonyms": ["active"]}]},
        ],
    }]
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Count owned assets",
        "SELECT COUNT(*) FROM public.assets WHERE ownership_status = 'O'",
        entities,
    )


def test_unrelated_entity_conflicting_attribute_synonyms_do_not_block_query():
    entities = [{
        "name": "Assets", "schema_name": "public", "table_name": "assets",
        "attributes": [
            {"column_name": "ownership_status", "value_mappings": [
                {"canonical_value": "O", "synonyms": ["active"]}]},
            {"column_name": "operating_status", "value_mappings": [
                {"canonical_value": "A", "synonyms": ["active"]}]},
        ],
    }]
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Count active customers",
        "SELECT COUNT(*) FROM public.customers",
        entities,
    )


def test_relevant_entity_conflicting_attribute_synonyms_still_fail():
    entities = [{
        "name": "Assets", "schema_name": "public", "table_name": "assets",
        "attributes": [
            {"column_name": "ownership_status", "value_mappings": [
                {"canonical_value": "O", "synonyms": ["active"]}]},
            {"column_name": "operating_status", "value_mappings": [
                {"canonical_value": "A", "synonyms": ["active"]}]},
        ],
    }]
    with pytest.raises(SQLValidationError) as captured:
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Count active assets",
            "SELECT COUNT(*) FROM public.assets",
            entities,
        )
    assert captured.value.details["checks"][0]["code"] == "categorical_attribute_ambiguity"
