"""Array membership cannot be satisfied by incidental SQL text."""
import pytest
from datapilot.application.services.query_correctness import assess_query_correctness


def _status(sql):
    checks = assess_query_correctness(
        affected_tables=["public.items"],
        governed_tables=["public.items"],
        sql=sql,
        required_filters=[{
            "column_name": "tags", "operator": "=",
            "value": "LNG", "data_type": "text[]",
        }],
    )
    return next(c["status"] for c in checks if c["code"] in {
        "filter_alignment", "filter_violation",
    })


@pytest.mark.parametrize("sql", [
    "SELECT tags FROM public.items WHERE tags @> ARRAY['LNG']",
    "SELECT tags FROM public.items WHERE active = TRUE AND tags @> ARRAY['LNG']",
    "SELECT tags FROM public.items WHERE 'LNG' = ANY(tags)",
])
def test_guaranteed_array_membership(sql):
    assert _status(sql) == "passed"


@pytest.mark.parametrize("sql", [
    "SELECT tags FROM public.items WHERE tags @> ARRAY['LNG'] OR active = TRUE",
    "SELECT tags FROM public.items WHERE NOT (tags @> ARRAY['LNG'])",
    "SELECT tags @> ARRAY['LNG'] AS matched FROM public.items",
    "SELECT tags FROM public.items WHERE active = TRUE OR tags @> ARRAY['LNG']",
    "SELECT tags FROM public.items WHERE tags @> ARRAY['LPG']",
    "SELECT tags FROM public.items WHERE other_tags @> ARRAY['LNG']",
])
def test_non_guaranteed_array_membership(sql):
    assert _status(sql) == "failed"
