"""Read-only publication readiness from trusted persisted metadata.

Readiness is not publication. The SQL execution path must not consume this
status as a grant until a transactional publisher and catalog isolation exist.
"""
from __future__ import annotations

from dataclasses import dataclass

from datapilot.application.relationship_freshness import assess_verification_freshness
from datapilot.application.relationship_publication import assess_relationship_publication


@dataclass(frozen=True)
class RelationshipReadiness:
    ready: bool
    reasons: tuple[str, ...]


async def assess_persisted_relationship_readiness(
    metadata, source_id: int, review: dict,
) -> RelationshipReadiness:
    """Fetch authoritative review and verification; ignore caller-supplied flags."""
    keys = ("from_schema", "from_table", "from_column",
            "to_schema", "to_table", "to_column")
    if not isinstance(source_id, int) or isinstance(source_id, bool) or source_id <= 0:
        return RelationshipReadiness(False, ("Invalid data source.",))
    if not isinstance(review, dict) or any(not isinstance(review.get(k), str) or not review[k] for k in keys):
        return RelationshipReadiness(False, ("Invalid relationship identity.",))
    reviews = await metadata.list_reviewed_relationships(source_id)
    matches = [
        candidate for candidate in reviews
        if all(candidate.get(key) == review[key] for key in keys)
    ]
    if len(matches) != 1:
        return RelationshipReadiness(False, ("Relationship review is missing or ambiguous.",))
    persisted = matches[0]
    evidence = await metadata.get_relationship_verification(source_id, persisted)
    freshness = assess_verification_freshness(persisted, evidence)
    if not freshness.current:
        return RelationshipReadiness(False, freshness.reasons)
    eligibility = assess_relationship_publication(
        persisted,
        structural_valid=evidence.get("structurally_valid") is True,
        live_cardinality_verified=evidence.get("live_cardinality_verified") is True,
        cardinality_holds=evidence.get("cardinality_holds") is True,
        referential_integrity_checked=evidence.get("referential_integrity_checked") is True,
        unmatched_references=evidence.get("unmatched_references"),
        nullable_references=evidence.get("nullable_references"),
        policy_enforced_by_sql_governance=False,
    )
    # SQL enforcement cannot be established by this read-only metadata check.
    return RelationshipReadiness(False, eligibility.reasons or
                                 ("SQL publication enforcement is not activated.",))
