"""Build an analytical binding context from authoritative metadata records.

This adapter never infers publication from retrieval ranking, missing fields,
or a generic 'enabled' flag. Callers must provide explicit publication
authorization obtained from their metadata governance layer.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from datapilot.application.services.published_analytical_context import PublishedSemanticContext


def build_published_analytical_context(
    *,
    datasource: str,
    metrics: Iterable[Mapping[str, Any]],
    dimensions: Iterable[Mapping[str, Any]],
    time_dimensions: Iterable[Mapping[str, Any]] = (),
    is_published: Callable[[str, Mapping[str, Any]], bool],
) -> PublishedSemanticContext:
    """Construct an isolated snapshot, refusing unapproved metadata.

    is_published must be backed by an authoritative, datasource-scoped
    publication decision. Do not supply an LLM-derived or client-supplied
    callback. Existing metadata records may not expose a publication field.
    """
    if not callable(is_published):
        raise ValueError("An authoritative publication checker is required")

    def approved(kind: str, records: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
        result: list[dict[str, Any]] = []
        for record in records:
            if not isinstance(record, Mapping):
                raise ValueError(f"Invalid {kind} metadata record")
            if record.get("datasource") != datasource:
                raise ValueError(f"Datasource mismatch in {kind} metadata")
            if not is_published(kind, record):
                raise ValueError(f"Unpublished {kind} metadata")
            name = record.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Unnamed {kind} metadata")
            # Only retain identifiers used by the binding contract. Avoid
            # retaining mutable provider payloads or arbitrary LLM metadata.
            result.append({
                "name": name,
                "datasource": datasource,
                "published": True,
            })
        return tuple(result)

    return PublishedSemanticContext(
        datasource=datasource,
        metrics=approved("metric", metrics),
        dimensions=approved("dimension", dimensions),
        time_dimensions=approved("time_dimension", time_dimensions),
    )
