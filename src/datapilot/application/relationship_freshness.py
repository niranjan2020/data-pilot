"""Conservative age and validity checks for persisted relationship verification.

A recent timestamp is necessary but never sufficient for publication:
the caller must still perform fresh live database verification and enforce SQL.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from datapilot.application.relationship_evidence import verification_matches_review


@dataclass(frozen=True)
class EvidenceFreshness:
    current: bool
    reasons: tuple[str, ...]


def assess_verification_freshness(
    review: dict, evidence: dict | None, *, now: datetime | None = None,
    max_age: timedelta = timedelta(minutes=15),
) -> EvidenceFreshness:
    reasons = []
    if not verification_matches_review(review, evidence):
        reasons.append("Verification does not match the current review.")
    if not isinstance(evidence, dict):
        return EvidenceFreshness(False, tuple(reasons))
    raw = evidence.get("verified_at")
    try:
        if not isinstance(raw, str):
            raise ValueError("Timestamp is missing.")
        verified = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if verified.tzinfo is None or verified.utcoffset() is None:
            raise ValueError("Timestamp has no timezone.")
        clock = now or datetime.now(timezone.utc)
        if clock.tzinfo is None or clock.utcoffset() is None:
            raise ValueError("Clock has no timezone.")
        if max_age <= timedelta(0):
            raise ValueError("Age threshold must be positive.")
        elapsed = clock.astimezone(timezone.utc) - verified.astimezone(timezone.utc)
        if elapsed < timedelta(0):
            reasons.append("Verification timestamp is in the future.")
        elif elapsed > max_age:
            reasons.append("Verification evidence has expired.")
    except (ValueError, TypeError, OverflowError):
        reasons.append("Verification timestamp is invalid.")
    for field in ("structurally_valid", "live_cardinality_verified",
                  "cardinality_holds", "referential_integrity_checked"):
        if evidence.get(field) is not True:
            reasons.append(f"Missing successful {field} evidence.")
    if evidence.get("unmatched_references") is not False:
        reasons.append("Unmatched reference evidence is not clear.")
    if not isinstance(evidence.get("nullable_references"), bool):
        reasons.append("Nullable reference evidence is unavailable.")
    return EvidenceFreshness(not reasons, tuple(reasons))
