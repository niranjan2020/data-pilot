"""Relationship review fingerprint regression tests."""

import pytest

from datapilot.application.relationship_evidence import (
    review_fingerprint,
    verification_matches_review,
)


REVIEW = {
    "from_schema": "astra", "from_table": "fixtures", "from_column": "vessel_id",
    "to_schema": "astra", "to_table": "vessels", "to_column": "id",
    "cardinality": "many_to_one", "join_policy": "matched_only",
    "review_status": "approved",
}


@pytest.mark.parametrize("field,change", [
    ("from_schema", "other"), ("from_table", "other"),
    ("from_column", "other"), ("to_schema", "other"),
    ("to_table", "other"), ("to_column", "other"),
    ("cardinality", "one_to_many"), ("join_policy", "preserve_source"),
    ("review_status", "rejected"),
])
def test_review_contract_changes_invalidate_prior_verification(field, change):
    evidence = {"review_fingerprint": review_fingerprint(REVIEW)}
    assert not verification_matches_review({**REVIEW, field: change}, evidence)


@pytest.mark.parametrize("field", list(REVIEW))
def test_missing_review_fields_fail_closed(field):
    review = dict(REVIEW)
    del review[field]
    with pytest.raises(ValueError):
        review_fingerprint(review)
    assert not verification_matches_review(review, {"review_fingerprint": "x"})


@pytest.mark.parametrize("value", [None, 0, 1, True, [], {}, ""])
def test_invalid_review_values_fail_closed(value):
    review = {**REVIEW, "join_policy": value}
    with pytest.raises(ValueError):
        review_fingerprint(review)


@pytest.mark.parametrize("evidence", [
    None, {}, {"review_fingerprint": None},
    {"review_fingerprint": 123}, {"review_fingerprint": "invalid"},
])
def test_missing_or_malformed_evidence_is_rejected(evidence):
    assert not verification_matches_review(REVIEW, evidence)


def test_same_review_produces_stable_digest():
    assert review_fingerprint(REVIEW) == review_fingerprint(dict(reversed(list(REVIEW.items()))))


def test_equivalent_identifier_case_and_whitespace_normalizes():
    altered = {**REVIEW, "from_schema": " ASTRA ", "join_policy": "MATCHED_ONLY"}
    assert review_fingerprint(REVIEW) == review_fingerprint(altered)


def test_matching_evidence_is_only_identity_check_not_publication():
    assert verification_matches_review(
        REVIEW, {"review_fingerprint": review_fingerprint(REVIEW)}
    )
