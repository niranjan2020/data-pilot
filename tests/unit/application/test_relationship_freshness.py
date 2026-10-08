"""Freshness regression matrix for persisted relationship verification."""
from datetime import datetime, timedelta, timezone

import pytest

from datapilot.application.relationship_evidence import review_fingerprint
from datapilot.application.relationship_freshness import assess_verification_freshness


NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
REVIEW = {
    "from_schema": "sales", "from_table": "orders", "from_column": "customer_id",
    "to_schema": "sales", "to_table": "customers", "to_column": "id",
    "cardinality": "many_to_one", "join_policy": "matched_only",
    "review_status": "approved",
}


def proof():
    return {
        "review_fingerprint": review_fingerprint(REVIEW),
        "verified_at": (NOW - timedelta(minutes=1)).isoformat(),
        "structurally_valid": True, "live_cardinality_verified": True,
        "cardinality_holds": True, "referential_integrity_checked": True,
        "unmatched_references": False, "nullable_references": False,
    }


def valid(evidence, **kwargs):
    return assess_verification_freshness(REVIEW, evidence, now=NOW, **kwargs).current


def test_recent_matching_evidence_is_current():
    assert valid(proof())


@pytest.mark.parametrize("minutes", [0, 1, 5, 14, 15])
def test_recent_boundaries(minutes):
    evidence = {**proof(), "verified_at": (NOW - timedelta(minutes=minutes)).isoformat()}
    assert valid(evidence)


@pytest.mark.parametrize("minutes", [16, 30, 60, 1440, 10080])
def test_expired_evidence(minutes):
    evidence = {**proof(), "verified_at": (NOW - timedelta(minutes=minutes)).isoformat()}
    assert not valid(evidence)


@pytest.mark.parametrize("minutes", [1, 5, 15, 60])
def test_future_evidence(minutes):
    evidence = {**proof(), "verified_at": (NOW + timedelta(minutes=minutes)).isoformat()}
    assert not valid(evidence)


@pytest.mark.parametrize("timestamp", [
    None, "", "bad", "2026-10-08T12:00:00", 123, True,
    "2026-13-01T00:00:00Z", "2026-10-08", [],
])
def test_invalid_timestamps(timestamp):
    assert not valid({**proof(), "verified_at": timestamp})


@pytest.mark.parametrize("field", [
    "structurally_valid", "live_cardinality_verified",
    "cardinality_holds", "referential_integrity_checked",
])
@pytest.mark.parametrize("value", [False, None, 0, "true"])
def test_failed_checks(field, value):
    assert not valid({**proof(), field: value})


@pytest.mark.parametrize("value", [True, None, 0, "false", ""])
def test_unmatched_references_not_clear(value):
    assert not valid({**proof(), "unmatched_references": value})


@pytest.mark.parametrize("value", [None, 0, 1, "false", "", []])
def test_missing_nullable_reference_evidence(value):
    assert not valid({**proof(), "nullable_references": value})


@pytest.mark.parametrize("field,value", [
    ("from_schema", "other"), ("from_table", "other"),
    ("from_column", "other"), ("to_schema", "other"),
    ("to_table", "other"), ("to_column", "other"),
    ("cardinality", "one_to_one"), ("join_policy", "preserve_source"),
    ("review_status", "rejected"),
])
def test_changed_review_is_stale(field, value):
    review = {**REVIEW, field: value}
    assert not assess_verification_freshness(review, proof(), now=NOW).current


@pytest.mark.parametrize("evidence", [None, {}, {"verified_at": NOW.isoformat()}])
def test_missing_evidence(evidence):
    assert not valid(evidence)


@pytest.mark.parametrize("seconds", [1, 30, 60, 300])
def test_custom_max_age(seconds):
    assert not valid(proof(), max_age=timedelta(seconds=seconds))


def test_iso_zulu_timestamp_supported():
    assert valid({**proof(), "verified_at": "2026-10-08T11:59:00Z"})


def test_offset_timestamp_supported():
    assert valid({**proof(), "verified_at": "2026-10-08T17:29:00+05:30"})


@pytest.mark.parametrize("minutes", [0, -1])
def test_invalid_max_age(minutes):
    assert not valid(proof(), max_age=timedelta(minutes=minutes))
