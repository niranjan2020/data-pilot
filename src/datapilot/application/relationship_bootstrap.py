"""Conservative relationship candidates; only declared constraints are verified."""
from __future__ import annotations

from pydantic import BaseModel


class RelationshipCandidate(BaseModel):
    from_schema: str
    from_table: str
    from_column: str
    to_schema: str
    to_table: str
    to_column: str
    provenance: str
    verified: bool
    status: str = "draft"


def propose_relationships(catalog: list[dict], selected: list[dict], foreign_keys: list[dict]) -> list[RelationshipCandidate]:
    by_key = {(t["schema_name"], t["table_name"]): t for t in catalog}
    allowed = {(t["schema_name"], t["table_name"]) for t in selected}
    columns = {key: {col["name"] for col in by_key[key]["columns"]} for key in allowed if key in by_key}
    results: list[RelationshipCandidate] = []
    seen: set[tuple[str, ...]] = set()

    def add(source: tuple[str, str], source_col: str, target: tuple[str, str], target_col: str, provenance: str, verified: bool) -> None:
        identity = (*source, source_col, *target, target_col)
        if identity not in seen:
            seen.add(identity)
            results.append(RelationshipCandidate(
                from_schema=source[0], from_table=source[1], from_column=source_col,
                to_schema=target[0], to_table=target[1], to_column=target_col,
                provenance=provenance, verified=verified,
            ))

    for fk in foreign_keys:
        source = (fk["schema_name"], fk["table_name"])
        # A qualified target is unambiguous. Unqualified names resolve only within
        # the source schema; never guess an across-schema foreign key.
        raw_target = fk["referenced_table"]
        if "." in raw_target:
            schema, table = raw_target.rsplit(".", 1)
            target = (schema.strip('"'), table.strip('"'))
        else:
            target = (source[0], raw_target)
        if source in allowed and target in allowed and fk["from_column"] in columns.get(source, set()) and fk["to_column"] in columns.get(target, set()):
            add(source, fk["from_column"], target, fk["to_column"], "declared_foreign_key", True)

    for source in sorted(allowed):
        for target in sorted(allowed):
            if source == target or source not in columns or target not in columns:
                continue
            # Only propose an explicit <target_table>_id -> id naming match.
            # This is NOT evidence of a valid join or cardinality.
            target_name = target[1]
            candidates = {target_name + "_id"}
            if target_name.endswith("s"):
                candidates.add(target_name[:-1] + "_id")
            for column in sorted(columns[source] & candidates):
                if "id" in columns[target]:
                    identity = (*source, column, *target, "id")
                    if identity not in seen:
                        add(source, column, target, "id", "column_name_heuristic", False)
    return results
