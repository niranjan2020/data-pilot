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
