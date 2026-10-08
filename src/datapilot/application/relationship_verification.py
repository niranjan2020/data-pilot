"""Fail-closed structural preflight for reviewed joins.

This does not verify live row-level cardinality or publish governed joins.
"""
from __future__ import annotations

from pydantic import BaseModel


class RelationshipPreflight(BaseModel):
    structurally_valid: bool
    live_cardinality_verified: bool = False
    publishable: bool = False
    reasons: list[str]


def preflight_relationship(review: dict, catalog: list[dict], foreign_keys: list[dict]) -> RelationshipPreflight:
    reasons: list[str] = []
    tables = {(t["schema_name"], t["table_name"]): t for t in catalog}
    source = tables.get((review["from_schema"], review["from_table"]))
    target = tables.get((review["to_schema"], review["to_table"]))
    if not source or not target:
        return RelationshipPreflight(structurally_valid=False, reasons=["Source or target table is absent from current discovery."])
    from_col = next((c for c in source["columns"] if c["name"] == review["from_column"]), None)
    to_col = next((c for c in target["columns"] if c["name"] == review["to_column"]), None)
    if not from_col or not to_col:
        return RelationshipPreflight(structurally_valid=False, reasons=["Join column is absent from current discovery."])
    from_type = str(from_col.get("data_type") or "").lower()
    to_type = str(to_col.get("data_type") or "").lower()
    if not from_type or not to_type or from_type != to_type:
        reasons.append("Join column types are missing or not identical; manual compatibility verification is required.")
    if review.get("review_status") != "approved":
        reasons.append("Human relationship approval is required.")
    cardinality = review.get("cardinality")
    if cardinality not in {"many_to_one", "one_to_many", "one_to_one", "many_to_many"}:
        reasons.append("Cardinality has not been reviewed.")
    if cardinality in {"many_to_one", "one_to_one"} and not to_col.get("is_primary_key"):
        reasons.append("Target join column is not confirmed unique by discovered primary-key metadata.")
    if cardinality in {"one_to_many", "one_to_one"} and not from_col.get("is_primary_key"):
        reasons.append("Source join column is not confirmed unique by discovered primary-key metadata.")
    if cardinality == "many_to_many":
        reasons.append("Many-to-many joins require explicit fan-out handling.")
    if not any(
        fk.get("schema_name") == review["from_schema"]
        and fk.get("table_name") == review["from_table"]
        and fk.get("from_column") == review["from_column"]
        and fk.get("referenced_table") in {review["to_table"], review["to_schema"] + "." + review["to_table"]}
        and fk.get("to_column") == review["to_column"]
        for fk in foreign_keys
    ):
        reasons.append("No matching declared foreign key found in current discovery.")
    return RelationshipPreflight(structurally_valid=not reasons, reasons=reasons)
