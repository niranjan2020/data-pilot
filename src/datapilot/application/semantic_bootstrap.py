"""Conservative, deterministic semantic bootstrap proposals.

Only discovered physical metadata is used. Proposals are never published
automatically; business meaning, calculations and joins require review.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DatasetProposal(BaseModel):
    schema_name: str
    table_name: str
    suggested_name: str
    description: str
    key_columns: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)
    provenance: str = "discovered_schema"
    status: str = "draft"
    warnings: list[str] = Field(default_factory=list)


def propose_datasets(catalog: list[dict], selected: list[dict]) -> list[DatasetProposal]:
    """Draft semantics for selected, discovered datasets only; no invented metrics."""
    by_key = {(t["schema_name"], t["table_name"]): t for t in catalog}
    proposals = []
    for item in selected:
        key = (item["schema_name"], item["table_name"])
        table = by_key.get(key)
        if table is None:
            raise ValueError("Selected dataset is not in the discovered catalog")
        columns = table["columns"]
        keys = [c["name"] for c in columns if c.get("is_primary_key")]
        warnings = ["Business meaning and grain require human approval."]
        if not keys:
            warnings.append("No primary key discovered; row identity is unknown.")
        proposals.append(DatasetProposal(
            schema_name=key[0],
            table_name=key[1],
            suggested_name=key[1].replace("_", " ").strip(),
            description=f"Discovered dataset {key[0]}.{key[1]} ({len(columns)} columns).",
            key_columns=keys,
            attributes=[c["name"] for c in columns],
            warnings=warnings,
        ))
    return proposals
