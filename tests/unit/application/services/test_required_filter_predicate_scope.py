"""Required filters must constrain every row, not merely occur in SQL."""
import pytest
from datapilot.application.services.query_correctness import assess_query_correctness


def _check(sql):
    checks = assess_query_correctness(
        affected_tables=["public.items"],
        governed_tables=["public.items"],
        sql=sql,
        required_filters=[{"column_name": "status", "operator": "=", "value": "O"}],
    )
    return next(c for c in checks if c["code"] in {"filter_alignment", "filter_violation"})


@pytest.mark.parametrize("sql", [
    "SELECT status FROM public.items WHERE status = 'O'",
    "SELECT status FROM public.items WHERE active = TRUE AND status = 'O'",
    "SELECT status FROM public.items WHERE status = 'O' AND active = TRUE",
    "SELECT status FROM public.items WHERE 'O' = status",
])
def test_outer_conjunction_guarantees_filter(sql):
    assert _check(sql)["status"] == "passed"


@pytest.mark.parametrize("sql", [
    "SELECT status = 'O' AS matched FROM public.items",
    "SELECT status FROM public.items WHERE status = 'O' OR active = TRUE",
    "SELECT status FROM public.items WHERE NOT (status = 'O')",
    "SELECT status FROM public.items GROUP BY status HAVING MAX(status) = 'O'",
    "SELECT status FROM public.items WHERE active = TRUE OR status = 'O'",
    "SELECT status FROM public.items WHERE active = TRUE AND (status = 'O' OR status = 'T')",
    "SELECT status FROM public.items WHERE status = 'T'",
])
def test_non_guaranteed_occurrences_are_rejected(sql):
    assert _check(sql)["status"] == "failed"
