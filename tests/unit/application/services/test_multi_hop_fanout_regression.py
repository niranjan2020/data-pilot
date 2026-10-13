"""P0: multi-hop metric grain regressions against the existing correctness engine.

These are generic semantic models, not customer-specific SQL templates.
"""
from datapilot.application.services.query_correctness import assess_query_correctness


RELATIONSHIPS = [
    {"name": "Account Transactions", "from_entity_id": 1, "to_entity_id": 2,
     "from_table": "public.accounts", "to_table": "public.transactions",
     "from_column": "id", "to_column": "account_id",
     "cardinality": "one-to-many"},
    {"name": "Transaction Items", "from_entity_id": 2, "to_entity_id": 3,
     "from_table": "public.transactions", "to_table": "public.items",
     "from_column": "id", "to_column": "transaction_id",
     "cardinality": "one-to-many"},
]
SQL = (
    "SELECT a.region, SUM(a.balance) AS balance "
    "FROM public.accounts a "
    "JOIN public.transactions t ON a.id = t.account_id "
    "JOIN public.items i ON t.id = i.transaction_id "
    "GROUP BY a.region"
)


def _checks(metrics, sql=SQL):
    return assess_query_correctness(
        affected_tables=["public.accounts", "public.transactions", "public.items"],
        governed_tables=["public.accounts", "public.transactions", "public.items"],
        sql=sql,
        governed_metrics=metrics,
        required_relationships=RELATIONSHIPS,
    )


def test_multi_hop_sum_on_one_side_rejects_fanout():
    checks = _checks([{"name": "Balance", "entity_id": 1,
                       "aggregation": "sum"}])
    assert any(c["code"] == "join_fanout_violation"
               and c.get("relationship") == "Account Transactions"
               for c in checks)


def test_multi_hop_count_on_one_side_rejects_fanout():
    checks = _checks([{"name": "Account Count", "entity_id": 1,
                       "aggregation": "count"}])
    assert any(c["code"] == "join_fanout_violation" for c in checks)


def test_multi_hop_distinct_count_does_not_raise_additive_fanout():
    sql = SQL.replace("SUM(a.balance)", "COUNT(DISTINCT a.id)")
    checks = _checks([{"name": "Distinct Accounts", "entity_id": 1,
                       "aggregation": "count_distinct"}], sql)
    assert not any(c["code"] == "join_fanout_violation" for c in checks)


def test_multi_hop_metric_on_middle_one_side_rejects_second_edge():
    sql = SQL.replace("SUM(a.balance)", "SUM(t.amount)")
    checks = _checks([{"name": "Transaction Amount", "entity_id": 2,
                       "aggregation": "sum"}], sql)
    assert any(c["code"] == "join_fanout_violation"
               and c.get("relationship") == "Transaction Items"
               for c in checks)
