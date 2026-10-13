from datapilot.application.services.published_grouping_guard import check_published_grouping

ENTITIES = [
    {"id": 1, "schema_name": "public", "table_name": "transactions"},
    {"id": 2, "schema_name": "public", "table_name": "accounts"},
]
DIMENSIONS = [{"entity_id": 2, "name": "Region", "column_name": "region", "synonyms": []}]


def verify(sql, question="transaction count by region", dims=DIMENSIONS):
    return check_published_grouping(sql, question, dims, ENTITIES)


def test_valid_joined_dimension():
    sql = ("SELECT a.region, COUNT(DISTINCT t.id) FROM public.transactions t "
           "JOIN public.accounts a ON t.account_id=a.id GROUP BY a.region")
    assert verify(sql) == ()


def test_similarly_named_column_on_wrong_entity_rejected():
    sql = ("SELECT t.region_next, COUNT(DISTINCT t.id) "
           "FROM public.transactions t GROUP BY t.region_next")
    assert verify(sql)


def test_same_column_name_on_wrong_entity_rejected():
    sql = ("SELECT t.region, COUNT(*) FROM public.transactions t GROUP BY t.region")
    assert verify(sql)


def test_unpublished_dimension_not_inferred_from_physical_schema():
    sql = "SELECT t.region_next, COUNT(*) FROM public.transactions t GROUP BY t.region_next"
    assert verify(sql, question="count by region_next") == ()


def test_ambiguous_published_owner_rejected():
    dims = DIMENSIONS + [{"entity_id": 1, "name": "Region", "column_name": "region"}]
    sql = "SELECT t.region, COUNT(*) FROM public.transactions t GROUP BY t.region"
    assert verify(sql, dims=dims)


def test_missing_grouping_rejected():
    assert verify("SELECT COUNT(*) FROM public.transactions")


def test_unrelated_technical_join_key_not_prohibited_by_grouping_guard():
    sql = ("SELECT a.region, COUNT(DISTINCT t.id) FROM public.transactions t "
           "JOIN public.accounts a ON t.account_id=a.id GROUP BY a.region")
    assert verify(sql) == ()


def test_grouping_guard_actually_checks_explicit_by_intent():
    sql = "SELECT t.region_next, COUNT(*) FROM public.transactions t GROUP BY t.region_next"
    errors = verify(sql, question="show transaction count by region")
    assert errors and "GROUP BY" in errors[0]


def test_correct_grouping_but_wrong_projection_is_rejected():
    sql = ("SELECT t.region_next, COUNT(*) FROM public.transactions t "
           "JOIN public.accounts a ON t.account_id = a.id GROUP BY a.region, t.region_next")
    errors = verify(sql)
    assert errors and "SELECT" in errors[0]


def test_published_grouping_projection_with_alias_is_accepted():
    sql = ("SELECT a.region AS area, COUNT(DISTINCT t.id) AS total "
           "FROM public.transactions t JOIN public.accounts a "
           "ON t.account_id = a.id GROUP BY a.region")
    assert verify(sql) == ()


def test_group_by_projection_alias_uses_published_source():
    sql = ("SELECT a.region AS area, COUNT(*) FROM public.accounts a "
           "GROUP BY area")
    assert verify(sql) == ()


def test_group_by_ordinal_uses_published_source():
    sql = ("SELECT a.region, COUNT(*) FROM public.accounts a GROUP BY 1")
    assert verify(sql) == ()


def test_alias_cannot_hide_unpublished_similar_column():
    sql = ("SELECT t.region_next AS region, COUNT(*) "
           "FROM public.transactions t GROUP BY region")
    assert verify(sql)


def test_ordinal_cannot_hide_wrong_entity_column():
    sql = ("SELECT t.region, COUNT(*) FROM public.transactions t GROUP BY 1")
    assert verify(sql)


def test_cte_approved_dimension_lineage():
    sql = ("WITH grouped AS (SELECT a.region AS territory FROM public.accounts a) "
           "SELECT g.territory, COUNT(*) FROM grouped g GROUP BY g.territory")
    assert verify(sql) == ()


def test_cte_wrong_physical_owner_rejected():
    sql = ("WITH grouped AS (SELECT t.region_next AS territory "
           "FROM public.transactions t) SELECT g.territory, COUNT(*) "
           "FROM grouped g GROUP BY g.territory")
    assert verify(sql)


def test_inline_subquery_approved_dimension_lineage():
    sql = ("SELECT g.territory, COUNT(*) FROM "
           "(SELECT a.region AS territory FROM public.accounts a) g "
           "GROUP BY g.territory")
    assert verify(sql) == ()


def test_nested_ctes_preserve_published_lineage():
    sql = ("WITH first AS (SELECT a.region AS territory FROM public.accounts a), "
           "second AS (SELECT f.territory AS area FROM first f) "
           "SELECT s.area, COUNT(*) FROM second s GROUP BY s.area")
    assert verify(sql) == ()


def test_computed_dimension_is_not_accepted_as_direct_published_dimension():
    sql = ("SELECT LOWER(a.region) AS territory, COUNT(*) "
           "FROM public.accounts a GROUP BY 1")
    assert verify(sql)


def test_nested_scalar_subquery_cannot_shadow_grouping_alias():
    sql = ("SELECT a.region, (SELECT MAX(t.region) FROM public.transactions t) AS other "
           "FROM public.accounts a GROUP BY a.region")
    assert verify(sql) == ()


def test_nested_scalar_subquery_cannot_supply_missing_published_dimension():
    sql = ("SELECT t.region, (SELECT MAX(a.region) FROM public.accounts a) AS other "
           "FROM public.transactions t GROUP BY t.region")
    assert verify(sql)


def test_duplicate_source_alias_cannot_prove_published_lineage():
    sql = ("SELECT a.region, COUNT(*) FROM public.accounts a "
           "JOIN public.transactions a ON a.id = a.account_id GROUP BY a.region")
    assert verify(sql)


def test_derived_table_wrong_owner_cannot_substitute():
    sql = ("SELECT x.region, COUNT(*) FROM "
           "(SELECT t.region AS region FROM public.transactions t) x "
           "GROUP BY x.region")
    assert verify(sql)


def test_duplicate_cte_names_cannot_authorize_published_dimension():
    sql = ("WITH source AS (SELECT a.region FROM public.accounts a), "
           "source AS (SELECT t.region FROM public.transactions t) "
           "SELECT s.region, COUNT(*) FROM source s GROUP BY s.region")
    assert verify(sql)


def test_non_select_cte_cannot_authorize_published_dimension():
    sql = ("WITH source AS (VALUES ('north')) "
           "SELECT s.column1 AS region, COUNT(*) FROM source s GROUP BY s.column1")
    assert verify(sql)
