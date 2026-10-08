"""Regression tests for source-rooted multi-table join governance."""
import pytest

from datapilot.application.join_policy_governance import validate_governed_join_graph
from datapilot.application.services.query_correctness import assess_query_correctness


RELATIONSHIPS = [
    dict(name="event_asset", from_schema="demo", from_table="demo.events",
         from_column="asset_id", to_schema="demo", to_table="demo.assets",
         to_column="id", cardinality="many_to_one", join_policy="preserve_source"),
    dict(name="asset_owner", from_schema="demo", from_table="demo.assets",
         from_column="owner_id", to_schema="demo", to_table="demo.owners",
         to_column="id", cardinality="many_to_one", join_policy="preserve_source"),
]
VALID = ("SELECT e.id FROM demo.events e "
         "LEFT JOIN demo.assets a ON e.asset_id = a.id "
         "LEFT JOIN demo.owners o ON a.owner_id = o.id")


@pytest.mark.parametrize("sql,allowed", [
    (VALID, True),
    (VALID.replace("LEFT JOIN demo.owners", "INNER JOIN demo.owners"), False),
    (VALID.replace("a.owner_id = o.id", "a.id = o.id"), False),
    (VALID + " LEFT JOIN demo.unknown u ON o.id = u.id", False),
    (VALID.replace("demo.owners o", "owners o"), False),
    (VALID.replace("a.owner_id = o.id", "a.owner_id = o.id OR 1=1"), False),
])
def test_all_edges_must_be_approved(sql, allowed):
    assert validate_governed_join_graph(sql, RELATIONSHIPS).allowed is allowed


def test_missing_published_edge_is_rejected():
    assert not validate_governed_join_graph(VALID, RELATIONSHIPS[:1]).allowed


def test_shared_correctness_gate_accepts_approved_chain():
    checks = assess_query_correctness(
        sql=VALID,
        affected_tables=["demo.events", "demo.assets", "demo.owners"],
        governed_tables=["demo.events", "demo.assets", "demo.owners"],
        required_relationships=RELATIONSHIPS,
    )
    assert any(c["code"] == "join_policy_alignment" for c in checks)
    assert not any(c["code"] == "join_policy_violation" for c in checks)


def test_shared_correctness_gate_rejects_unapproved_chain():
    sql = VALID.replace("LEFT JOIN demo.owners", "INNER JOIN demo.owners")
    checks = assess_query_correctness(
        sql=sql,
        affected_tables=["demo.events", "demo.assets", "demo.owners"],
        governed_tables=["demo.events", "demo.assets", "demo.owners"],
        required_relationships=RELATIONSHIPS,
    )
    assert any(c["code"] == "join_policy_violation" and c["status"] == "failed" for c in checks)


def test_one_governed_edge_cannot_authorize_extra_sql_join():
    checks = assess_query_correctness(
        sql=VALID,
        affected_tables=["demo.events", "demo.assets", "demo.owners"],
        governed_tables=["demo.events", "demo.assets", "demo.owners"],
        required_relationships=RELATIONSHIPS[:1],
    )
    assert any(c["code"] == "join_policy_violation" and c["status"] == "failed" for c in checks)


def test_distinct_approved_paths_can_be_selected_by_exact_join_keys():
    alternate = {
        **RELATIONSHIPS[1], "name": "asset_billing_owner",
        "from_column": "billing_owner_id",
    }
    checks = assess_query_correctness(
        sql=VALID,
        affected_tables=["demo.events", "demo.assets", "demo.owners"],
        governed_tables=["demo.events", "demo.assets", "demo.owners"],
        required_relationships=[*RELATIONSHIPS, alternate],
    )
    assert any(c["code"] == "join_policy_alignment" for c in checks)
    assert not any(c["code"] == "join_policy_violation" for c in checks)


def test_duplicate_matching_approved_paths_are_ambiguous():
    assert not validate_governed_join_graph(VALID, [*RELATIONSHIPS, dict(RELATIONSHIPS[1])]).allowed


def test_unapproved_extra_join_rejected_even_when_table_is_governed():
    extra = VALID + " LEFT JOIN demo.regions r ON o.region_id = r.id"
    checks = assess_query_correctness(
        sql=extra,
        affected_tables=["demo.events", "demo.assets", "demo.owners", "demo.regions"],
        governed_tables=["demo.events", "demo.assets", "demo.owners", "demo.regions"],
        required_relationships=RELATIONSHIPS,
    )
    assert any(c["code"] == "join_policy_violation" and c["status"] == "failed" for c in checks)


def test_projection_cte_with_governed_join_chain():
    sql = "WITH joined AS (" + VALID + ") SELECT id FROM joined"
    assert validate_governed_join_graph(sql, RELATIONSHIPS).allowed


def test_projection_cte_rejects_unsafe_inner_join():
    sql = "WITH joined AS (" + VALID.replace("LEFT JOIN demo.owners", "INNER JOIN demo.owners") + ") SELECT id FROM joined"
    assert not validate_governed_join_graph(sql, RELATIONSHIPS).allowed


def test_projection_cte_rejects_ungoverned_outer_join():
    sql = "WITH joined AS (" + VALID + ") SELECT j.id FROM joined j JOIN demo.other x ON j.id = x.id"
    assert not validate_governed_join_graph(sql, RELATIONSHIPS).allowed


def test_projection_cte_rejects_multiple_ctes():
    sql = "WITH joined AS (" + VALID + "), other AS (SELECT 1 AS id) SELECT id FROM joined"
    assert not validate_governed_join_graph(sql, RELATIONSHIPS).allowed


def test_shared_correctness_gate_checks_cte_join_policy():
    sql = "WITH joined AS (" + VALID + ") SELECT id FROM joined"
    checks = assess_query_correctness(
        sql=sql,
        affected_tables=["demo.events", "demo.assets", "demo.owners"],
        governed_tables=["demo.events", "demo.assets", "demo.owners"],
        required_relationships=RELATIONSHIPS,
    )
    assert any(c["code"] == "join_policy_alignment" and c["status"] == "passed" for c in checks)
