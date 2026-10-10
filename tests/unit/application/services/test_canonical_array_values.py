"""Canonical PostgreSQL array literal validation from governed metadata."""
import pytest

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.core.exceptions import SQLValidationError


ENTITIES = [{
    "name": "Items", "schema_name": "public", "table_name": "items",
    "attributes": [{
        "name": "Tags", "column_name": "tags", "data_type": "text[]",
        "value_mappings": [
            {"canonical_value": "Alpha", "synonyms": ["alpha tag"]},
            {"canonical_value": "Beta", "synonyms": ["beta tag"]},
        ],
    }],
}]


def validate(question, sql, entities=ENTITIES):
    QueryOrchestrator._validate_canonical_array_literals(question, sql, entities)


def test_rejects_wrong_case_for_published_array_element():
    with pytest.raises(SQLValidationError, match="noncanonical"):
        validate(
            "Find items with alpha tag",
            "SELECT id FROM public.items WHERE tags @> ARRAY['alpha']",
        )


def test_accepts_exact_canonical_array_element():
    validate(
        "Find items with alpha tag",
        "SELECT id FROM public.items WHERE tags @> ARRAY['Alpha']",
    )


def test_ignores_unrelated_unpublished_array_elements():
    validate(
        "Find items with gamma tag",
        "SELECT id FROM public.items WHERE tags @> ARRAY['gamma']",
    )


def test_ignores_unrelated_table():
    validate(
        "Find items with alpha tag",
        "SELECT id FROM public.other WHERE tags @> ARRAY['alpha']",
    )


def test_rejects_case_mismatch_in_multi_value_array():
    with pytest.raises(SQLValidationError, match="noncanonical"):
        validate(
            "Find items with alpha tag and beta tag",
            "SELECT id FROM public.items WHERE tags @> ARRAY['Alpha', 'beta']",
        )


def test_rejects_missing_second_requested_canonical_array_value():
    with pytest.raises(SQLValidationError, match="omitted requested"):
        validate(
            "Find items with alpha tag and beta tag",
            "SELECT id FROM public.items WHERE tags @> ARRAY['Alpha']",
        )


def test_accepts_all_requested_array_values():
    validate(
        "Find items with alpha tag and beta tag",
        "SELECT id FROM public.items WHERE tags @> ARRAY['Alpha', 'Beta']",
    )


def test_does_not_require_literal_array_filter_for_unnest_grouping():
    validate(
        "Show counts for alpha tag and beta tag",
        "SELECT tag, COUNT(*) FROM public.items CROSS JOIN LATERAL UNNEST(tags) AS tag GROUP BY tag",
    )

def test_repairs_single_case_only_containment_literal():
    original = "SELECT id FROM public.items WHERE tags @> ARRAY['alpha']"
    with pytest.raises(SQLValidationError) as captured:
        validate("Find items with alpha tag", original)
    repaired = QueryOrchestrator._repair_canonical_array_literal(original, captured.value)
    assert repaired is not None
    assert "ARRAY['Alpha']" in repaired
    validate("Find items with alpha tag", repaired)


def test_repair_does_not_guess_missing_array_category():
    original = "SELECT id FROM public.items WHERE tags @> ARRAY['Alpha']"
    with pytest.raises(SQLValidationError) as captured:
        validate("Find items with alpha tag and beta tag", original)
    assert QueryOrchestrator._repair_canonical_array_literal(original, captured.value) is None


def test_repair_rejects_joined_queries():
    original = "SELECT i.id FROM public.items i JOIN public.other o ON i.id = o.id WHERE i.tags @> ARRAY['alpha']"
    with pytest.raises(SQLValidationError) as captured:
        validate("Find items with alpha tag", original)
    assert QueryOrchestrator._repair_canonical_array_literal(original, captured.value) is None


def test_repair_rejects_or_predicates():
    original = "SELECT id FROM public.items WHERE tags @> ARRAY['alpha'] OR id = 1"
    with pytest.raises(SQLValidationError) as captured:
        validate("Find items with alpha tag", original)
    assert QueryOrchestrator._repair_canonical_array_literal(original, captured.value) is None
