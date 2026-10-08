"""Bind relationship verification evidence to the exact approved review.

A digest is a change-detection identifier, not a cryptographic attestation of
database state. Publication must still require fresh trusted live checks.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


REVIEW_FIELDS = (
    "from_schema", "from_table", "from_column",
    "to_schema", "to_table", "to_column",
    "cardinality", "join_policy", "review_status",
)


def review_fingerprint(review: dict[str, Any]) -> str:
    """Produce a stable identity for the join contract being verified."""
    values = {}
    for field in REVIEW_FIELDS:
        value = review.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing or invalid review field: {field}")
        values[field] = value.strip().casefold()
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verification_matches_review(
    review: dict[str, Any], evidence: dict[str, Any] | None
) -> bool:
    """Reject absent, malformed, or stale review-bound verification evidence."""
    if not isinstance(evidence, dict):
        return False
    fingerprint = evidence.get("review_fingerprint")
    if not isinstance(fingerprint, str):
        return False
    try:
        return fingerprint == review_fingerprint(review)
    except ValueError:
        return False
