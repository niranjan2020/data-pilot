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


def test_explicit_attribute_resolves_shared_categorical_synonym():
    entities = [{
        "name": "Assets", "schema_name": "public", "table_name": "assets",
        "attributes": [
            {"name": "Ownership Status", "column_name": "ownership_status",
             "value_mappings": [{"canonical_value": "O", "synonyms": ["active"]}]},
            {"name": "Operating Status", "column_name": "operating_status",
             "value_mappings": [{"canonical_value": "A", "synonyms": ["active"]}]},
        ],
    }]
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Count assets with active operating status",
        "SELECT COUNT(*) FROM public.assets WHERE operating_status = 'A'",
        entities,
    )


def test_explicit_attribute_does_not_accept_other_columns_filter():
    entities = [{
        "name": "Assets", "schema_name": "public", "table_name": "assets",
        "attributes": [
            {"name": "Ownership Status", "column_name": "ownership_status",
             "value_mappings": [{"canonical_value": "O", "synonyms": ["active"]}]},
            {"name": "Operating Status", "column_name": "operating_status",
             "value_mappings": [{"canonical_value": "A", "synonyms": ["active"]}]},
        ],
    }]
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Count assets with active operating status",
            "SELECT COUNT(*) FROM public.assets WHERE ownership_status = 'O'",
            entities,
        )


def test_shared_value_synonym_offers_attribute_clarification_before_sql():
    entities = [{
        "name": "Assets",
        "attributes": [
            {"name": "Ownership Status", "column_name": "ownership_status",
             "value_mappings": [{"canonical_value": "O", "synonyms": ["active"]}]},
            {"name": "Operating Status", "column_name": "operating_status",
             "value_mappings": [{"canonical_value": "A", "synonyms": ["active"]}]},
        ],
    }]
    candidates = QueryOrchestrator._ambiguous_attribute_matches("Count active assets", entities)
    assert {c["value"] for c in candidates} == {
        "Assets.Ownership Status", "Assets.Operating Status"
    }


def test_explicit_attribute_suppresses_shared_value_clarification():
    entities = [{
        "name": "Assets",
        "attributes": [
            {"name": "Ownership Status", "column_name": "ownership_status",
             "value_mappings": [{"canonical_value": "O", "synonyms": ["active"]}]},
            {"name": "Operating Status", "column_name": "operating_status",
             "value_mappings": [{"canonical_value": "A", "synonyms": ["active"]}]},
        ],
    }]
    assert QueryOrchestrator._ambiguous_attribute_matches(
        "Count assets with active operating status", entities
    ) == []


def test_clarified_attribute_enforces_only_selected_categorical_column():
    entities = [{
        "name": "Assets", "schema_name": "public", "table_name": "assets",
        "attributes": [
            {"name": "Ownership Status", "column_name": "ownership_status",
             "value_mappings": [{"canonical_value": "O", "synonyms": ["active"]}]},
            {"name": "Operating Status", "column_name": "operating_status",
             "value_mappings": [{"canonical_value": "A", "synonyms": ["active"]}]},
        ],
    }]
    selection = {"entity": "Assets", "attribute": "Operating Status",
                 "column_name": "operating_status"}
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Count active assets",
        "SELECT COUNT(*) FROM public.assets WHERE operating_status = 'A'",
        entities, selected_attribute=selection,
    )
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Count active assets",
            "SELECT COUNT(*) FROM public.assets WHERE ownership_status = 'O'",
            entities, selected_attribute=selection,
        )


# Astra-style published categories are fixture data, not domain-specific logic.
@pytest.mark.parametrize(("question", "expected"), [
    ("Show owned vessels", "O"),
    ("Show time chartered vessels", "T"),
    ("Show owned but currently chartered vessels", "TO"),
])
def test_published_ownership_category_requires_exact_canonical_filter(question, expected):
    entities = [{
        "name": "Vessels", "schema_name": "astra", "table_name": "vessel_snapshot",
        "attributes": [{"name": "Ownership Status", "column_name": "ownership_status",
                        "value_mappings": [
                            {"canonical_value": "O", "synonyms": ["owned vessel", "owned"]},
                            {"canonical_value": "T", "synonyms": ["time chartered vessel", "chartered vessel"]},
                            {"canonical_value": "TO", "synonyms": ["owned but currently chartered"]},
                        ]}],
    }]
    sql = (
        "SELECT COUNT(*) FROM astra.vessel_snapshot "
        f"WHERE ownership_status = '{expected}'"
    )
    QueryOrchestrator._validate_explicit_categorical_comparison(question, sql, entities)
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            question, "SELECT COUNT(*) FROM astra.vessel_snapshot", entities,
        )


@pytest.mark.parametrize('data_type', ['integer', 'int4', 'bigint', 'numeric', 'date', 'timestamp'])
def test_numeric_and_temporal_between_not_treated_as_categorical(data_type):
    entities = [{'name': 'Events', 'table_name': 'events', 'attributes': [{
        'column_name': 'event_year', 'data_type': data_type,
        'value_mappings': [{'canonical_value': '2020'}, {'canonical_value': '2021'}],
    }]}]
    QueryOrchestrator._validate_explicit_categorical_comparison(
        'Show events between 2020 and 2021',
        'SELECT COUNT(*) FROM events WHERE event_year BETWEEN 2020 AND 2021',
        entities,
    )


def test_textual_categorical_comparison_remains_governed():
    entities = [{'name': 'Events', 'table_name': 'events', 'attributes': [{
        'column_name': 'period_label', 'data_type': 'text',
        'value_mappings': [{'canonical_value': '2020'}, {'canonical_value': '2021'}],
    }]}]
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            'Compare 2020 versus 2021',
            'SELECT COUNT(*) FROM events',
            entities,
        )


# Production-path regression: connector tokens must not become category codes.
@pytest.mark.parametrize("question", [
    "Show assets built from 2015 to 2025",
    "Compare assets from 2020 to 2026",
    "Show assets between 2015 to 2025",
    "Count assets from 2018 to 2020 by ownership status",
])
def test_date_range_to_does_not_require_ownership_code(question):
    QueryOrchestrator._validate_explicit_categorical_comparison(
        question,
        "SELECT COUNT(*) FROM assets",
        ENTITIES,
    )


@pytest.mark.parametrize("question", [
    "Show assets with ownership status 'TO'",
    "Show owned but chartered assets",
])
def test_explicit_to_category_requires_sql_filter(question):
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            question,
            "SELECT COUNT(*) FROM assets",
            ENTITIES,
        )


@pytest.mark.parametrize("question", [
    "Show assets with ownership status 'TO'",
    "Show owned but chartered assets",
])
def test_explicit_to_category_accepts_correct_sql_filter(question):
    QueryOrchestrator._validate_explicit_categorical_comparison(
        question,
        "SELECT COUNT(*) FROM assets WHERE ownership_status = 'TO'",
        ENTITIES,
    )


@pytest.mark.parametrize(("question", "predicate"), [
    ("Count LNG-capable assets", "alternative_fuel_type @> ARRAY['LNG']"),
    ("Count LNG-capable assets", "'LNG' = ANY(alternative_fuel_type)"),
    ("Count LNG-capable assets", "alternative_fuel_type && ARRAY['LNG', 'Methanol']"),
    ("Count assets with both LNG and methanol", "alternative_fuel_type @> ARRAY['LNG', 'Methanol']"),
])
def test_governed_array_categories_accept_postgres_membership(question, predicate):
    entities = [{
        "name": "Assets", "schema_name": "public", "table_name": "assets",
        "attributes": [{
            "name": "Alternative Fuel Type", "column_name": "alternative_fuel_type",
            "data_type": "text[]",
            "value_mappings": [
                {"canonical_value": "LNG", "synonyms": ["lng-capable"]},
                {"canonical_value": "Methanol", "synonyms": ["methanol"]},
            ],
        }],
    }]
    sql = f"SELECT COUNT(*) FROM public.assets WHERE {predicate}"
    QueryOrchestrator._validate_explicit_categorical_comparison(question, sql, entities)


@pytest.mark.parametrize("predicate", [
    "alternative_fuel_type && ARRAY['LNG', 'Methanol']",
    "'LNG' = ANY(alternative_fuel_type)",
    "alternative_fuel_type @> ARRAY['LNG']",
])
def test_governed_array_both_categories_rejects_any_of_filter(predicate):
    entities = [{
        "name": "Assets", "schema_name": "public", "table_name": "assets",
        "attributes": [{
            "name": "Alternative Fuel Type", "column_name": "alternative_fuel_type",
            "data_type": "text[]",
            "value_mappings": [
                {"canonical_value": "LNG", "synonyms": ["lng"]},
                {"canonical_value": "Methanol", "synonyms": ["methanol"]},
            ],
        }],
    }]
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Count assets with both LNG and methanol",
            f"SELECT COUNT(*) FROM public.assets WHERE {predicate}",
            entities,
        )


FUEL_ENTITIES = [{
    "name": "Inventory", "schema_name": "public", "table_name": "inventory",
    "attributes": [{
        "column_name": "fuel_types", "data_type": "text[]",
        "value_mappings": [
            {"canonical_value": "LNG", "synonyms": ["lng"]},
            {"canonical_value": "Methanol", "synonyms": ["methanol"]},
        ],
    }],
}]


def test_comparison_accepts_separate_conditional_array_aggregates():
    sql = (
        "SELECT category, "
        "COUNT(CASE WHEN 'LNG' = ANY(fuel_types) THEN id END) AS lng_count, "
        "COUNT(CASE WHEN 'Methanol' = ANY(fuel_types) THEN id END) AS methanol_count "
        "FROM public.inventory GROUP BY category"
    )
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Compare LNG and methanol inventory counts by category", sql, FUEL_ENTITIES
    )


def test_comparison_accepts_conjunctive_array_membership_for_both_values():
    sql = (
        "SELECT COUNT(*) FROM public.inventory WHERE "
        "'LNG' = ANY(fuel_types) AND 'Methanol' = ANY(fuel_types)"
    )
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "How many inventory items have both LNG and methanol?", sql, FUEL_ENTITIES
    )


@pytest.mark.parametrize("where", [
    "'LNG' = ANY(fuel_types) OR 'Methanol' = ANY(fuel_types)",
    "'LNG' = ANY(fuel_types) AND 'LNG' = ANY(fuel_types)",
    "'LNG' = ANY(fuel_types) AND 'methanol' = ANY(fuel_types)",
])
def test_comparison_rejects_nonconjunctive_or_noncanonical_array_values(where):
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "How many inventory items have both LNG and methanol?",
            "SELECT COUNT(*) FROM public.inventory WHERE " + where, FUEL_ENTITIES
        )


# Regression cases reproduced from generic PostgreSQL array comparisons.
ARRAY_ENTITIES = [{
    "name": "Items", "schema_name": "public", "table_name": "items",
    "attributes": [{
        "column_name": "tags", "data_type": "text[]",
        "value_mappings": [
            {"canonical_value": "Alpha", "synonyms": ["alpha capable"]},
            {"canonical_value": "Beta", "synonyms": ["beta capable"]},
        ],
    }],
}]


def test_array_comparison_accepts_independent_filtered_aggregates():
    sql = (
        "SELECT i.category, "
        "COUNT(DISTINCT i.id) FILTER (WHERE 'Alpha' = ANY(i.tags)) AS alpha_count, "
        "COUNT(DISTINCT i.id) FILTER (WHERE 'Beta' = ANY(i.tags)) AS beta_count "
        "FROM public.items AS i GROUP BY i.category"
    )
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Compare alpha capable and beta capable item counts by category",
        sql, ARRAY_ENTITIES,
    )


def test_array_comparison_accepts_expanded_cohorts():
    sql = (
        "SELECT i.category, t.tag, COUNT(DISTINCT i.id) "
        "FROM public.items AS i, UNNEST(i.tags) AS t(tag) "
        "WHERE t.tag IN ('Alpha', 'Beta') "
        "GROUP BY i.category, t.tag"
    )
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Compare alpha capable and beta capable item counts by category",
        sql, ARRAY_ENTITIES,
    )


def test_array_comparison_rejects_unrelated_expansion():
    sql = (
        "SELECT i.category, t.tag, COUNT(DISTINCT i.id) "
        "FROM public.items AS i, UNNEST(i.other_tags) AS t(tag) "
        "WHERE t.tag IN ('Alpha', 'Beta') "
        "GROUP BY i.category, t.tag"
    )
    with pytest.raises(SQLValidationError):
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare alpha capable and beta capable item counts by category",
            sql, ARRAY_ENTITIES,
        )


def test_array_comparison_repair_removes_redundant_scalar_in():
    sql = (
        "SELECT i.category, "
        "COUNT(DISTINCT i.id) FILTER (WHERE 'Alpha' = ANY(i.tags)) AS alpha_count, "
        "COUNT(DISTINCT i.id) FILTER (WHERE 'Beta' = ANY(i.tags)) AS beta_count "
        "FROM public.items AS i "
        "WHERE i.active = TRUE AND i.tags IN ('Alpha', 'Beta') "
        "GROUP BY i.category"
    )
    with pytest.raises(SQLValidationError) as captured:
        QueryOrchestrator._validate_explicit_categorical_comparison(
            "Compare alpha capable and beta capable item counts by category",
            sql, ARRAY_ENTITIES,
        )
    repaired = QueryOrchestrator._repair_explicit_categorical_comparison(sql, captured.value)
    assert repaired is not None
    assert "i.active" in repaired.lower()
    assert "TAGS IN" not in repaired.upper()
    QueryOrchestrator._validate_explicit_categorical_comparison(
        "Compare alpha capable and beta capable item counts by category",
        repaired, ARRAY_ENTITIES,
    )
