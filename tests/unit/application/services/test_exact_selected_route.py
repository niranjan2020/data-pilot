"""Exact selected relationship routes cannot be shortened or substituted."""
import pytest

from datapilot.application.published_join_authorization import (
    authorize_exact_selected_route_sql,
)


ROUTE = [
    {"from_schema": "public", "from_table": "transactions",
     "from_column": "bridge_id", "to_schema": "public",
     "to_table": "bridges", "to_column": "id",
     "cardinality": "many_to_one", "join_policy": "preserve_source"},
    {"from_schema": "public", "from_table": "bridges",
     "from_column": "region_id", "to_schema": "public",
     "to_table": "regions", "to_column": "id",
     "cardinality": "many_to_one", "join_policy": "preserve_source"},
]


def test_exact_selected_route_accepts_both_governed_edges():
    sql = """SELECT t.id FROM public.transactions t
    LEFT JOIN public.bridges b ON t.bridge_id = b.id
    LEFT JOIN public.regions r ON b.region_id = r.id"""
    assert authorize_exact_selected_route_sql(sql, ROUTE).allowed


@pytest.mark.parametrize("sql", [
    "SELECT t.id FROM public.transactions t LEFT JOIN public.bridges b ON t.bridge_id = b.id",
    """SELECT t.id FROM public.transactions t
       LEFT JOIN public.alternative_bridges b ON t.bridge_id = b.id
       LEFT JOIN public.regions r ON b.region_id = r.id""",
    """SELECT t.id FROM public.transactions t
       LEFT JOIN public.bridges b ON t.bridge_id = b.id
       LEFT JOIN public.regions r ON b.other_region_id = r.id""",
    """SELECT t.id FROM public.bridges b
       LEFT JOIN public.transactions t ON b.id = t.bridge_id
       LEFT JOIN public.regions r ON b.region_id = r.id""",
])
def test_exact_selected_route_rejects_shortened_or_changed_sql(sql):
    assert not authorize_exact_selected_route_sql(sql, ROUTE).allowed


def test_semantic_contract_preserves_selected_route_as_independent_snapshot():
    from datapilot.application.services.semantic_intent_contract import SemanticIntentContract

    selected = [dict(ROUTE[0])]
    contract = SemanticIntentContract.from_governed_context(
        {"metrics": [], "resolved_attribute_selection": None},
        grouping_columns=[], required_filters=[], required_relationships=[],
        time_plan=None, selected_relationship_route=selected,
    )
    selected[0]["to_table"] = "tampered"
    assert contract.selected_relationship_route[0]["to_table"] == "bridges"
    snapshot = contract.as_dict()
    assert snapshot["selected_relationship_route"][0]["to_table"] == "bridges"
    snapshot["selected_relationship_route"][0]["to_table"] = "tampered"
    assert contract.selected_relationship_route[0]["to_table"] == "bridges"
