"""Regression coverage for generic array and conditional-comparison SQL checks."""

from datapilot.application.services.query_correctness import assess_query_correctness


def _codes(sql: str) -> set[str]:
    return {
        check["code"]
        for check in assess_query_correctness(
            sql=sql, affected_tables=["public.items"],
            governed_tables=["public.items"], dialect="postgresql",
        )
        if check["status"] == "failed"
    }


def test_rejects_unnest_inside_group_by():
    sql = (
        "SELECT UNNEST(tags) AS tag, COUNT(*) FROM public.items "
        "GROUP BY UNNEST(tags)"
    )
    assert "array_expansion_grouping_violation" in _codes(sql)


def test_accepts_lateral_array_expansion_grouping():
    sql = (
        "SELECT x.tag, COUNT(DISTINCT i.id) FROM public.items AS i "
        "CROSS JOIN LATERAL UNNEST(i.tags) AS x(tag) GROUP BY x.tag"
    )
    assert "array_expansion_grouping_violation" not in _codes(sql)


def test_rejects_split_conditional_period_comparison():
    sql = (
        "SELECT owner, COUNT(CASE WHEN period = 2020 THEN id END), "
        "COUNT(CASE WHEN period = 2021 THEN id END) FROM public.items "
        "GROUP BY owner, period"
    )
    assert "conditional_comparison_grain_violation" in _codes(sql)


def test_accepts_comparison_at_owner_grain():
    sql = (
        "SELECT owner, COUNT(CASE WHEN period = 2020 THEN id END), "
        "COUNT(CASE WHEN period = 2021 THEN id END) FROM public.items "
        "GROUP BY owner"
    )
    assert "conditional_comparison_grain_violation" not in _codes(sql)


def test_rejects_conditional_in_grouping_discriminator():
    sql = (
        'SELECT owner, SUM(CASE WHEN period IN (2020, 2021) THEN 1 ELSE 0 END) '
        'FROM public.items GROUP BY owner, period'
    )
    assert 'conditional_comparison_grain_violation' in _codes(sql)


def test_accepts_conditional_in_at_owner_grain():
    sql = (
        'SELECT owner, SUM(CASE WHEN period IN (2020, 2021) THEN 1 ELSE 0 END) '
        'FROM public.items GROUP BY owner'
    )
    assert 'conditional_comparison_grain_violation' not in _codes(sql)


def test_rejects_conditional_between_grouping_discriminator():
    sql = (
        'SELECT owner, SUM(CASE WHEN period BETWEEN 2020 AND 2021 THEN 1 ELSE 0 END) '
        'FROM public.items GROUP BY owner, period'
    )
    assert 'conditional_comparison_grain_violation' in _codes(sql)


def test_accepts_conditional_between_at_owner_grain():
    sql = (
        'SELECT owner, SUM(CASE WHEN period BETWEEN 2020 AND 2021 THEN 1 ELSE 0 END) '
        'FROM public.items GROUP BY owner'
    )
    assert 'conditional_comparison_grain_violation' not in _codes(sql)


def test_rejects_aggregate_filter_grouping_discriminator():
    sql = (
        'SELECT owner, COUNT(*) FILTER (WHERE period = 2020) '
        'FROM public.items GROUP BY owner, period'
    )
    assert 'conditional_comparison_grain_violation' in _codes(sql)


def test_accepts_aggregate_filter_at_owner_grain():
    sql = (
        'SELECT owner, COUNT(*) FILTER (WHERE period = 2020) '
        'FROM public.items GROUP BY owner'
    )
    assert 'conditional_comparison_grain_violation' not in _codes(sql)


def test_plain_grouped_count_not_mistaken_for_conditional_aggregate():
    sql = 'SELECT owner, period, COUNT(*) FROM public.items GROUP BY owner, period'
    assert 'conditional_comparison_grain_violation' not in _codes(sql)


def test_conditional_aggregate_grouped_by_unrelated_dimension_allowed():
    sql = (
        'SELECT category, COUNT(CASE WHEN period = 2020 THEN 1 END) '
        'FROM public.items GROUP BY category'
    )
    assert 'conditional_comparison_grain_violation' not in _codes(sql)
