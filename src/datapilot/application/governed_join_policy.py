"""Fail-closed SQL join policy contract for governed relationships.

This module validates publication intent. SQL activation must be separately
wired into the query validator before a relationship can be published.
"""
from __future__ import annotations

from dataclasses import dataclass

from datapilot.application.relationship_publication import assess_relationship_publication
from datapilot.application.relationship_evidence import verification_matches_review


@dataclass(frozen=True)
class GovernedJoinDecision:
    allowed: bool
    join_type: str | None
    reasons: tuple[str, ...]


def assess_governed_join(
    review: dict,
    evidence: dict | None,
    *,
    requested_join_type: str,
    sql_governance_enforced: bool = False,
    live_evidence_fresh: bool = False,
) -> GovernedJoinDecision:
    """Determine whether a reviewed join is eligible for its exact SQL semantics.

    INNER is required for matched_only; LEFT is required for preserve_source.
    RIGHT/FULL/CROSS/NATURAL and implicit joins never inherit approval.
    """
    policy = review.get("join_policy")
    expected = {"matched_only": "INNER", "preserve_source": "LEFT"}.get(policy)
    reasons = []
    requested = requested_join_type.strip().upper() if isinstance(requested_join_type, str) else ""
    if expected is None:
        reasons.append("An explicit supported join policy is required.")
    elif requested != expected:
        reasons.append(f"Join policy requires {expected} JOIN, not {requested or 'unspecified'} JOIN.")
    if not verification_matches_review(review, evidence):
        reasons.append("Verification evidence is missing or does not match the review.")
    if not live_evidence_fresh:
        reasons.append("Fresh live verification is required before SQL activation.")
    evidence = evidence if isinstance(evidence, dict) else {}
    eligibility = assess_relationship_publication(
        review,
        structural_valid=evidence.get("structurally_valid") is True,
        live_cardinality_verified=evidence.get("live_cardinality_verified") is True,
        cardinality_holds=evidence.get("cardinality_holds") is True,
        referential_integrity_checked=evidence.get("referential_integrity_checked") is True,
        unmatched_references=evidence.get("unmatched_references")
        if isinstance(evidence.get("unmatched_references"), bool) else None,
        nullable_references=evidence.get("nullable_references")
        if isinstance(evidence.get("nullable_references"), bool) else None,
        policy_enforced_by_sql_governance=sql_governance_enforced,
    )
    reasons.extend(eligibility.reasons)
    return GovernedJoinDecision(not reasons, expected, tuple(dict.fromkeys(reasons)))
