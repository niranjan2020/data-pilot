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


def _grain_codes(sql, question, required=('owner',)):
    return {check['code'] for check in assess_query_correctness(
        sql=sql, question=question, required_grouping_columns=required,
        affected_tables=['public.items'], governed_tables=['public.items'],
        dialect='postgresql',
    ) if check['status'] == 'failed'}


def test_explicit_grouping_rejects_extra_vessel_dimension():
    sql = 'SELECT owner, item_name, COUNT(*) FROM public.items GROUP BY owner, item_name'
    assert 'explicit_grouping_grain_violation' in _grain_codes(sql, 'Show items grouped by owner')


def test_explicit_grouping_accepts_exact_grain():
    sql = 'SELECT owner, COUNT(*) FROM public.items GROUP BY owner'
    assert 'explicit_grouping_grain_violation' not in _grain_codes(sql, 'Show items grouped by owner')


def test_unresolved_grain_does_not_guess():
    sql = 'SELECT owner, item_name, COUNT(*) FROM public.items GROUP BY owner, item_name'
    assert 'explicit_grouping_grain_violation' not in _grain_codes(sql, 'Show items grouped by owner', ())


def test_explicit_multiple_dimensions_accepted_when_governed():
    sql = 'SELECT owner, category, COUNT(*) FROM public.items GROUP BY owner, category'
    assert 'explicit_grouping_grain_violation' not in _grain_codes(
        sql, 'Show items grouped by owner and by category', ('owner', 'category')
    )


def test_implicit_grouping_does_not_enforce_exact_grain():
    sql = 'SELECT owner, item_name, COUNT(*) FROM public.items GROUP BY owner, item_name'
    assert 'explicit_grouping_grain_violation' not in _grain_codes(sql, 'Count items per owner')


def test_joined_query_does_not_guess_extra_grain():
    sql = ('SELECT i.owner, i.item_name, COUNT(*) FROM public.items i '
           'JOIN public.groups g ON g.id = i.group_id GROUP BY i.owner, i.item_name')
    assert 'explicit_grouping_grain_violation' not in _grain_codes(
        sql, 'Show items grouped by owner')


def test_missing_required_grouping_still_rejected():
    sql = 'SELECT category, COUNT(*) FROM public.items GROUP BY category'
    assert 'grouping_dimension_violation' in _grain_codes(sql, 'Show items grouped by owner')


def test_explicit_grouping_rejects_extra_date_dimension():
    sql = 'SELECT owner, period, COUNT(*) FROM public.items GROUP BY owner, period'
    assert 'explicit_grouping_grain_violation' in _grain_codes(sql, 'Show items grouped by owner')
