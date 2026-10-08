"""Broad join-policy contract matrix: never grant SQL activation implicitly."""
import pytest

from datapilot.application.governed_join_policy import assess_governed_join
from datapilot.application.relationship_evidence import review_fingerprint


BASE = {
    "from_schema": "demo", "from_table": "orders", "from_column": "customer_id",
    "to_schema": "demo", "to_table": "customers", "to_column": "id",
    "cardinality": "many_to_one", "review_status": "approved",
    "join_policy": "matched_only",
}


def proof(review=BASE):
    return {
        "review_fingerprint": review_fingerprint(review),
        "structurally_valid": True,
        "live_cardinality_verified": True,
        "cardinality_holds": True,
        "referential_integrity_checked": True,
        "unmatched_references": False,
        "nullable_references": False,
    }


@pytest.mark.parametrize("policy,join_type", [
    ("matched_only", "INNER"), ("preserve_source", "LEFT"),
])
def test_exact_approved_join_is_eligible_only_with_fresh_enforcement(policy, join_type):
    review = {**BASE, "join_policy": policy}
    result = assess_governed_join(review, proof(review), requested_join_type=join_type,
                                  sql_governance_enforced=True, live_evidence_fresh=True)
    assert result.allowed
    assert result.join_type == join_type


@pytest.mark.parametrize("policy", ["matched_only", "preserve_source", "unconfigured", "", "outer", None])
@pytest.mark.parametrize("join_type", ["INNER", "LEFT", "RIGHT", "FULL", "CROSS", "NATURAL", "JOIN", "", None])
def test_join_type_policy_matrix(policy, join_type):
    review = {**BASE, "join_policy": policy}
    evidence = proof(review) if isinstance(policy, str) and policy else None
    result = assess_governed_join(review, evidence, requested_join_type=join_type,
                                  sql_governance_enforced=True, live_evidence_fresh=True)
    expected = {"matched_only": "INNER", "preserve_source": "LEFT"}.get(policy)
    assert result.allowed is (expected is not None and join_type == expected)


@pytest.mark.parametrize("field,value", [
    ("structurally_valid", False),
    ("live_cardinality_verified", False),
    ("cardinality_holds", False),
    ("referential_integrity_checked", False),
    ("unmatched_references", True),
    ("unmatched_references", None),
    ("nullable_references", None),
    ("structurally_valid", 1),
    ("live_cardinality_verified", "true"),
    ("cardinality_holds", None),
    ("referential_integrity_checked", 1),
    ("unmatched_references", 0),
    ("nullable_references", "false"),
])
def test_bad_evidence_fails_closed(field, value):
    evidence = {**proof(), field: value}
    assert not assess_governed_join(BASE, evidence, requested_join_type="INNER",
                                    sql_governance_enforced=True, live_evidence_fresh=True).allowed


@pytest.mark.parametrize("field,value", [
    ("review_status", "rejected"),
    ("review_status", "pending"),
    ("cardinality", "one_to_many"),
    ("cardinality", "many_to_many"),
    ("cardinality", "unknown"),
    ("cardinality", ""),
])
def test_unapproved_or_fanout_contract_fails(field, value):
    review = {**BASE, field: value}
    evidence = proof(review) if value else proof()
    assert not assess_governed_join(review, evidence, requested_join_type="INNER",
                                    sql_governance_enforced=True, live_evidence_fresh=True).allowed


@pytest.mark.parametrize("enforced,fresh", [(False, False), (False, True), (True, False)])
def test_missing_enforcement_or_freshness_fails(enforced, fresh):
    assert not assess_governed_join(BASE, proof(), requested_join_type="INNER",
                                    sql_governance_enforced=enforced,
                                    live_evidence_fresh=fresh).allowed


@pytest.mark.parametrize("field,value", [
    ("from_schema", "other"), ("from_table", "other"),
    ("from_column", "other"), ("to_schema", "other"),
    ("to_table", "other"), ("to_column", "other"),
    ("cardinality", "one_to_one"), ("join_policy", "preserve_source"),
    ("review_status", "rejected"),
])
def test_stale_review_contract_rejected(field, value):
    review = {**BASE, field: value}
    assert not assess_governed_join(review, proof(), requested_join_type="INNER",
                                    sql_governance_enforced=True, live_evidence_fresh=True).allowed


@pytest.mark.parametrize("evidence", [None, {}, {"review_fingerprint": "bad"}, {"review_fingerprint": None}])
def test_missing_or_invalid_fingerprint_rejected(evidence):
    assert not assess_governed_join(BASE, evidence, requested_join_type="INNER",
                                    sql_governance_enforced=True, live_evidence_fresh=True).allowed


def test_whitespace_join_type_is_accepted_only_for_explicit_contract():
    assert assess_governed_join(BASE, proof(), requested_join_type=" INNER ",
                                sql_governance_enforced=True, live_evidence_fresh=True).allowed


def test_case_insensitive_sql_keyword():
    assert assess_governed_join(BASE, proof(), requested_join_type="inner",
                                sql_governance_enforced=True, live_evidence_fresh=True).allowed
