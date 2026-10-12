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
