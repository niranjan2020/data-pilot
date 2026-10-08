"""Fail-closed semantic relationship publication eligibility.

Eligibility is not publication: no catalog writes or SQL activation occur here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublicationEligibility:
    eligible: bool
    reasons: tuple[str, ...]


def assess_relationship_publication(
    review: dict,
    *,
    structural_valid: bool,
    live_cardinality_verified: bool,
    cardinality_holds: bool,
    referential_integrity_checked: bool,
    unmatched_references: bool | None,
    nullable_references: bool | None,
    policy_enforced_by_sql_governance: bool = False,
) -> PublicationEligibility:
    reasons: list[str] = []
    if review.get("review_status") != "approved":
        reasons.append("Relationship requires human approval.")
    if review.get("cardinality") not in {"many_to_one", "one_to_one"}:
        reasons.append("Relationship cardinality is not eligible for fan-out-safe publishing.")
    policy = review.get("join_policy", "unconfigured")
    if policy not in {"preserve_source", "matched_only"}:
        reasons.append("Explicit approved join policy is required.")
    if not structural_valid:
        reasons.append("Current discovered schema or foreign-key structure is not verified.")
    if not live_cardinality_verified or not cardinality_holds:
        reasons.append("Fresh live join-cardinality verification is required.")
    if not referential_integrity_checked or unmatched_references is None or nullable_references is None:
        reasons.append("Fresh referential-integrity evidence is required.")
    elif unmatched_references:
        reasons.append("Unmatched non-null references require remediation or explicit governance.")
    if not policy_enforced_by_sql_governance:
        reasons.append("SQL governance does not yet enforce the approved join policy.")
    return PublicationEligibility(eligible=not reasons, reasons=tuple(reasons))
