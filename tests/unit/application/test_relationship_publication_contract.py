"""C5 regression coverage for conservative relationship publication eligibility."""

import pytest

from datapilot.application.relationship_publication import assess_relationship_publication


REVIEW = {"review_status": "approved", "cardinality": "many_to_one", "join_policy": "matched_only"}
EVIDENCE = {
    "structural_valid": True,
    "live_cardinality_verified": True,
    "cardinality_holds": True,
    "referential_integrity_checked": True,
    "unmatched_references": False,
    "nullable_references": False,
    "policy_enforced_by_sql_governance": False,
}


@pytest.mark.parametrize("key,value", [
    ("structural_valid", False),
    ("live_cardinality_verified", False),
    ("cardinality_holds", False),
    ("referential_integrity_checked", False),
    ("unmatched_references", None),
    ("nullable_references", None),
    ("unmatched_references", True),
    ("policy_enforced_by_sql_governance", False),
])
def test_publication_rejected_without_complete_evidence(key, value):
    evidence = {**EVIDENCE, key: value, "policy_enforced_by_sql_governance": True}
    result = assess_relationship_publication(REVIEW, **evidence)
    assert not result.eligible
    assert result.reasons


@pytest.mark.parametrize("change", [
    {"review_status": "rejected"},
    {"review_status": "pending"},
    {"cardinality": "one_to_many"},
    {"cardinality": "many_to_many"},
    {"cardinality": "unknown"},
    {"join_policy": "unconfigured"},
    {"join_policy": ""},
])
def test_publication_rejected_for_unsafe_review(change):
    result = assess_relationship_publication(
        {**REVIEW, **change},
        **{**EVIDENCE, "policy_enforced_by_sql_governance": True},
    )
    assert not result.eligible


@pytest.mark.parametrize("policy", ["matched_only", "preserve_source"])
def test_complete_verified_policy_is_only_eligible_when_enforced(policy):
    result = assess_relationship_publication(
        {**REVIEW, "join_policy": policy},
        **{**EVIDENCE, "policy_enforced_by_sql_governance": True},
    )
    assert result.eligible
    assert result.reasons == ()


def test_current_runtime_does_not_publish_verified_relationship():
    result = assess_relationship_publication(REVIEW, **EVIDENCE)
    assert not result.eligible
    assert any("SQL governance" in reason for reason in result.reasons)
