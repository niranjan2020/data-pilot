"""Generic, governed nonempty-array filter regression tests."""
import pytest

from datapilot.application.services.query_orchestrator import QueryOrchestrator
from datapilot.core.exceptions import SQLValidationError

ENTITIES = [{"name": "Items", "attributes": [{
    "name": "Labels", "column_name": "labels",
    "data_type": "text[]", "synonyms": ["tags"],
}]}]


def test_rejects_null_only_for_explicitly_populated_array():
    with pytest.raises(SQLValidationError, match="nonempty array"):
        QueryOrchestrator._validate_nonempty_array_filters(
            "Show items with non-empty tags",
            "SELECT id FROM public.items WHERE labels IS NOT NULL",
            ENTITIES,
        )


def test_does_not_reject_explicit_positive_cardinality():
    QueryOrchestrator._validate_nonempty_array_filters(
        "Show items with non-empty tags",
        "SELECT id FROM public.items WHERE labels IS NOT NULL AND CARDINALITY(labels) > 0",
        ENTITIES,
    )


def test_does_not_infer_business_meaning_without_published_rule():
    QueryOrchestrator._validate_nonempty_array_filters(
        "Show capable items",
        "SELECT id FROM public.items WHERE labels IS NOT NULL",
        ENTITIES,
    )


def test_nonarray_attribute_does_not_trigger_array_rule():
    QueryOrchestrator._validate_nonempty_array_filters(
        "Show items with non-empty tags",
        "SELECT id FROM public.items WHERE labels IS NOT NULL",
        [{"name": "Items", "attributes": [{"name": "tags", "column_name": "labels", "data_type": "text"}]}],
    )


def test_rejects_null_only_plus_empty_array_equality():
    with pytest.raises(SQLValidationError, match="nonempty array"):
        QueryOrchestrator._validate_nonempty_array_filters(
            "Show items with non-empty tags",
            "SELECT id FROM public.items WHERE labels IS NOT NULL AND labels = ARRAY[]::TEXT[]",
            ENTITIES,
        )


def test_rejects_zero_cardinality_even_when_not_null():
    with pytest.raises(SQLValidationError, match="nonempty array"):
        QueryOrchestrator._validate_nonempty_array_filters(
            "Show items with non-empty tags",
            "SELECT id FROM public.items WHERE labels IS NOT NULL AND CARDINALITY(labels) = 0",
            ENTITIES,
        )


def test_accepts_positive_cardinality_with_unrelated_predicate():
    QueryOrchestrator._validate_nonempty_array_filters(
        "Show items with non-empty tags",
        "SELECT id FROM public.items WHERE labels IS NOT NULL AND CARDINALITY(labels) > 0 AND id > 1",
        ENTITIES,
    )


@pytest.mark.parametrize('sql', [
    'SELECT id FROM public.items',
    'SELECT id FROM public.items WHERE id > 1',
    'SELECT id FROM public.items WHERE labels = ARRAY[]::TEXT[]',
    'SELECT id FROM public.items WHERE CARDINALITY(labels) = 0',
    'SELECT id FROM public.items WHERE labels IS NOT NULL AND id > 1',
])
def test_explicit_nonempty_requires_positive_population_proof(sql):
    with pytest.raises(SQLValidationError, match='nonempty array'):
        QueryOrchestrator._validate_nonempty_array_filters(
            'Show items with non-empty tags', sql, ENTITIES,
        )


@pytest.mark.parametrize('sql', [
    'SELECT id FROM public.items WHERE CARDINALITY(labels) > 0',
    'SELECT id FROM public.items WHERE ARRAY_LENGTH(labels, 1) > 0',
    'SELECT id FROM public.items WHERE labels IS NOT NULL AND CARDINALITY(labels) > 0',
])
def test_explicit_nonempty_accepts_positive_population_without_null_guard(sql):
    QueryOrchestrator._validate_nonempty_array_filters(
        'Show items with non-empty tags', sql, ENTITIES,
    )


def test_unrelated_nonempty_attribute_does_not_require_labels_filter():
    QueryOrchestrator._validate_nonempty_array_filters(
        'Show items with non-empty descriptions',
        'SELECT id FROM public.items', ENTITIES,
    )


@pytest.mark.parametrize('sql', [
    'SELECT id FROM public.items',
    'SELECT id FROM public.items WHERE labels IS NOT NULL',
    'SELECT id FROM public.items WHERE id > 10',
])
def test_published_nonempty_phrase_requires_positive_filter(sql):
    entities = [{'name': 'Items', 'attributes': [{
        'name': 'Labels', 'column_name': 'labels', 'data_type': 'text[]',
        'nonempty_intent_phrases': ['label enabled', 'has labels'],
    }]}]
    with pytest.raises(SQLValidationError, match='nonempty array'):
        QueryOrchestrator._validate_nonempty_array_filters(
            'Show label enabled items', sql, entities,
        )


def test_published_nonempty_phrase_accepts_positive_cardinality():
    entities = [{'name': 'Items', 'attributes': [{
        'name': 'Labels', 'column_name': 'labels', 'data_type': 'text[]',
        'nonempty_intent_phrases': ['label enabled'],
    }]}]
    QueryOrchestrator._validate_nonempty_array_filters(
        'Show label enabled items',
        'SELECT id FROM public.items WHERE CARDINALITY(labels) > 0',
        entities,
    )


def test_unpublished_business_phrase_does_not_imply_nonempty():
    QueryOrchestrator._validate_nonempty_array_filters(
        'Show label enabled items',
        'SELECT id FROM public.items WHERE labels IS NOT NULL',
        ENTITIES,
    )


def test_governed_nonempty_phrase_is_attribute_scoped():
    entities = [{'name': 'Items', 'attributes': [{
        'name': 'Labels', 'column_name': 'labels', 'data_type': 'text[]',
        'nonempty_intent_phrases': ['label enabled'],
    }]}]
    QueryOrchestrator._validate_nonempty_array_filters(
        'Show category enabled items',
        'SELECT id FROM public.items',
        entities,
    )


def test_nonarray_attribute_does_not_apply_governed_nonempty_phrase():
    entities = [{'name': 'Items', 'attributes': [{
        'name': 'Labels', 'column_name': 'labels', 'data_type': 'text',
        'nonempty_intent_phrases': ['label enabled'],
    }]}]
    QueryOrchestrator._validate_nonempty_array_filters(
        'Show label enabled items',
        'SELECT id FROM public.items',
        entities,
    )


@pytest.mark.parametrize('sql', [
    'SELECT id FROM public.items WHERE CARDINALITY(labels) > 0 OR id > 1',
    'SELECT id FROM public.items WHERE NOT (CARDINALITY(labels) > 0)',
    'SELECT id FROM public.items WHERE (CARDINALITY(labels) > 0 OR id > 1) AND id > 0',
    'SELECT id FROM public.items WHERE labels IS NOT NULL AND (CARDINALITY(labels) > 0 OR id > 1)',
    'SELECT id FROM public.items WHERE CARDINALITY(labels) > 0 OR CARDINALITY(labels) = 0',
    'SELECT id FROM public.items WHERE COALESCE(CARDINALITY(labels), 0) > 0 OR id > 1',
])
def test_nonempty_guard_rejects_disjunctive_or_negated_cardinality(sql):
    with pytest.raises(SQLValidationError, match='nonempty array'):
        QueryOrchestrator._validate_nonempty_array_filters(
            'Show items with non-empty tags', sql, ENTITIES,
        )


@pytest.mark.parametrize('sql', [
    'SELECT id FROM public.items WHERE CARDINALITY(labels) > 0 AND id > 1',
    'SELECT id FROM public.items WHERE id > 1 AND CARDINALITY(labels) > 0',
    'SELECT id FROM public.items WHERE ARRAY_LENGTH(labels, 1) > 0 AND id > 1',
])
def test_nonempty_guard_accepts_standalone_positive_conjunct(sql):
    QueryOrchestrator._validate_nonempty_array_filters(
        'Show items with non-empty tags', sql, ENTITIES,
    )


def test_published_nonempty_phrase_rejects_disjunctive_cardinality():
    entities = [{'name': 'Items', 'attributes': [{
        'name': 'Labels', 'column_name': 'labels', 'data_type': 'text[]',
        'nonempty_intent_phrases': ['label enabled'],
    }]}]
    with pytest.raises(SQLValidationError, match='nonempty array'):
        QueryOrchestrator._validate_nonempty_array_filters(
            'Show label enabled items',
            'SELECT id FROM public.items WHERE CARDINALITY(labels) > 0 OR id > 1',
            entities,
        )
