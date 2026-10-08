"""Trusted metadata readiness cannot be forged by a request payload."""
import pytest

from datapilot.application.relationship_readiness import assess_persisted_relationship_readiness
from datapilot.application.relationship_evidence import review_fingerprint
from datetime import datetime, timezone


REVIEW = {
    "from_schema": "sales", "from_table": "orders", "from_column": "customer_id",
    "to_schema": "sales", "to_table": "customers", "to_column": "id",
    "cardinality": "many_to_one", "join_policy": "matched_only",
    "review_status": "approved",
}


class Metadata:
    def __init__(self, reviews=None, evidence=None):
        self.reviews = [REVIEW] if reviews is None else reviews
        self.evidence = evidence
        self.lookups = []

    async def list_reviewed_relationships(self, source):
        self.lookups.append(("reviews", source))
        return self.reviews

    async def get_relationship_verification(self, source, review):
        self.lookups.append(("verification", source, review))
        return self.evidence


def evidence():
    return {
        "review_fingerprint": review_fingerprint(REVIEW),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "structurally_valid": True, "live_cardinality_verified": True,
        "cardinality_holds": True, "referential_integrity_checked": True,
        "unmatched_references": False, "nullable_references": False,
    }


@pytest.mark.asyncio
async def test_valid_persisted_evidence_does_not_auto_publish():
    metadata = Metadata(evidence=evidence())
    result = await assess_persisted_relationship_readiness(metadata, 7, REVIEW)
    assert not result.ready
    assert "SQL governance" in " ".join(result.reasons)
    assert [item[0] for item in metadata.lookups] == ["reviews", "verification"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("review_status", "rejected"), ("join_policy", "unconfigured"),
    ("cardinality", "many_to_many"), ("from_table", "fake"),
    ("to_column", "fake"), ("sql_governance_enforced", True),
    ("live_evidence_fresh", True), ("verification_evidence", {"fake": True}),
])
async def test_request_cannot_override_persisted_review(field, value):
    metadata = Metadata(evidence=evidence())
    result = await assess_persisted_relationship_readiness(metadata, 7, {**REVIEW, field: value})
    assert not result.ready


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [0, -1, None, True, "7"])
async def test_invalid_source_never_reads_metadata(source):
    metadata = Metadata(evidence=evidence())
    result = await assess_persisted_relationship_readiness(metadata, source, REVIEW)
    assert not result.ready
    assert metadata.lookups == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reviews", [[], [REVIEW, REVIEW], [{**REVIEW, "from_table": "other"}]])
async def test_missing_or_ambiguous_review_fails(reviews):
    metadata = Metadata(reviews=reviews, evidence=evidence())
    result = await assess_persisted_relationship_readiness(metadata, 7, REVIEW)
    assert not result.ready
    assert all(item[0] != "verification" for item in metadata.lookups)


@pytest.mark.asyncio
@pytest.mark.parametrize("proof", [None, {}, {"verified_at": "invalid"}])
async def test_invalid_evidence_fails(proof):
    metadata = Metadata(evidence=proof)
    result = await assess_persisted_relationship_readiness(metadata, 7, REVIEW)
    assert not result.ready
