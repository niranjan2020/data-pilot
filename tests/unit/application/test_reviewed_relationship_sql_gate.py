"""Regression matrix for reviewed relationship publication gates in SQL correctness."""
import pytest

from datapilot.application.relationship_evidence import review_fingerprint
from datapilot.application.services.query_correctness import assess_query_correctness


REVIEW = {
    "from_schema": "sales", "from_table": "orders", "from_column": "customer_id",
    "to_schema": "sales", "to_table": "customers", "to_column": "id",
    "cardinality": "many_to_one", "join_policy": "matched_only",
    "review_status": "approved",
}
SQL = "SELECT o.id FROM sales.orders o INNER JOIN sales.customers c ON o.customer_id = c.id"


def checks(review, sql=SQL):
    return assess_query_correctness(
        affected_tables=["sales.orders", "sales.customers"],
        governed_tables=["sales.orders", "sales.customers"],
        sql=sql,
        required_relationships=[review],
    )


def publication(checks):
    return next(c for c in checks if c["code"].startswith("relationship_publication_"))


def evidence(review=REVIEW):
    return {
        "review_fingerprint": review_fingerprint(review),
        "structurally_valid": True, "live_cardinality_verified": True,
        "cardinality_holds": True, "referential_integrity_checked": True,
        "unmatched_references": False, "nullable_references": False,
    }


@pytest.mark.parametrize("field", [
    "verification_evidence", "sql_governance_enforced", "live_evidence_fresh",
])
def test_missing_authorization_fails(field):
    review = {**REVIEW, "verification_evidence": evidence(),
              "sql_governance_enforced": True, "live_evidence_fresh": True}
    del review[field]
    assert publication(checks(review))["status"] == "failed"


@pytest.mark.parametrize("field,value", [
    ("sql_governance_enforced", False), ("sql_governance_enforced", None),
    ("sql_governance_enforced", 1), ("sql_governance_enforced", "true"),
    ("live_evidence_fresh", False), ("live_evidence_fresh", None),
    ("live_evidence_fresh", 1), ("live_evidence_fresh", "true"),
    ("verification_evidence", None), ("verification_evidence", {}),
    ("verification_evidence", {"review_fingerprint": "bad"}),
])
def test_invalid_authorization_fails(field, value):
    review = {**REVIEW, "verification_evidence": evidence(),
              "sql_governance_enforced": True, "live_evidence_fresh": True, field: value}
    assert publication(checks(review))["status"] == "failed"


@pytest.mark.parametrize("field,value", [
    ("review_status", "rejected"), ("review_status", "pending"),
    ("cardinality", "one_to_many"), ("cardinality", "many_to_many"),
    ("cardinality", "unknown"), ("join_policy", "unconfigured"),
    ("join_policy", "preserve_source"),
])
def test_changed_review_cannot_reuse_evidence(field, value):
    review = {**REVIEW, "verification_evidence": evidence(),
              "sql_governance_enforced": True, "live_evidence_fresh": True, field: value}
    assert publication(checks(review))["status"] == "failed"


@pytest.mark.parametrize("field,value", [
    ("structurally_valid", False),
    ("live_cardinality_verified", False),
    ("cardinality_holds", False),
    ("referential_integrity_checked", False),
    ("unmatched_references", True),
    ("unmatched_references", None),
    ("nullable_references", None),
])
def test_invalid_live_evidence_fails(field, value):
    review = {**REVIEW, "verification_evidence": {**evidence(), field: value},
              "sql_governance_enforced": True, "live_evidence_fresh": True}
    assert publication(checks(review))["status"] == "failed"


def test_caller_claimed_authorization_cannot_publish_relationship():
    review = {**REVIEW, "verification_evidence": evidence(),
              "sql_governance_enforced": True, "live_evidence_fresh": True}
    assert publication(checks(review))["status"] == "failed"


def test_legacy_semantic_relationship_does_not_get_fake_review_gate():
    review = {key: value for key, value in REVIEW.items() if key != "review_status"}
    assert not any(c["code"].startswith("relationship_publication_") for c in checks(review))


@pytest.mark.parametrize("sql", [
    "SELECT o.id FROM sales.orders o LEFT JOIN sales.customers c ON o.customer_id = c.id",
    "SELECT o.id FROM sales.orders o RIGHT JOIN sales.customers c ON o.customer_id = c.id",
    "SELECT o.id FROM sales.orders o FULL JOIN sales.customers c ON o.customer_id = c.id",
    "SELECT o.id FROM sales.orders o CROSS JOIN sales.customers c",
    "SELECT o.id FROM sales.orders o INNER JOIN sales.customers c ON o.id = c.id",
    "SELECT o.id FROM sales.customers c INNER JOIN sales.orders o ON o.customer_id = c.id",
    "SELECT o.id FROM sales.orders o INNER JOIN sales.customers c ON o.customer_id = c.id OR o.id = c.id",
    "SELECT o.id FROM sales.orders o INNER JOIN sales.customers c ON o.customer_id = c.id AND c.id > 0",
    "SELECT o.id FROM sales.orders o JOIN sales.customers c USING (customer_id)",
    "SELECT o.id FROM sales.orders o",
    "SELECT 1",
    "INVALID SQL ???",
])
def test_reviewed_relationship_sql_mismatch_never_publishes(sql):
    review = {**REVIEW, "verification_evidence": evidence(),
              "sql_governance_enforced": True, "live_evidence_fresh": True}
    result = publication(checks(review, sql=sql))
    assert result["status"] == "failed"
    assert result["severity"] == "error"


@pytest.mark.parametrize("status", ["approved", "rejected", "pending", "", None])
@pytest.mark.parametrize("flag", [True, False, None, 1, "true"])
def test_caller_cannot_force_publication_with_flags(status, flag):
    review = {**REVIEW, "review_status": status,
              "verification_evidence": evidence(),
              "sql_governance_enforced": flag,
              "live_evidence_fresh": flag}
    assert publication(checks(review))["status"] == "failed"


def test_actual_sql_join_type_is_reported_as_violation():
    review = {**REVIEW, "verification_evidence": evidence(),
              "sql_governance_enforced": True, "live_evidence_fresh": True}
    wrong_sql = "SELECT o.id FROM sales.orders o LEFT JOIN sales.customers c ON o.customer_id = c.id"
    result = publication(checks(review, sql=wrong_sql))
    assert "Join type violates" in result["message"]
