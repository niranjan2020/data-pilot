"""Deterministic semantic entity and value resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from datapilot.domain.models import SchemaMetadata
from datapilot.domain.semantic import (
    EntityAttributeDefinition,
    EntityDefinition,
    QueryIntent,
    ResolvedEntity,
    ResolvedFilter,
    SemanticCatalog,
)


_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_QUOTED_VALUE_RE = r"""["']([^"']+)["']"""
_VALUE_RE = r"""([A-Za-z0-9][A-Za-z0-9 _.&'/-]*)"""


@dataclass(frozen=True)
class EntityMatch:
    entity: EntityDefinition
    score: float
    matched_terms: tuple[str, ...]


class DeterministicEntityResolver:
    """Resolve entities and explicit filter values using catalog semantics."""

    def __init__(self, *, minimum_entity_score: float = 0.25, ambiguity_margin: float = 0.10) -> None:
        self._minimum_entity_score = minimum_entity_score
        self._ambiguity_margin = ambiguity_margin

    def resolve(
        self,
        question: str,
        catalog: SemanticCatalog,
        schema: SchemaMetadata,
    ) -> QueryIntent:
        del schema

        matches = self._match_entities(question, catalog)
        if not matches:
            return QueryIntent()

        top = matches[0]
        if len(matches) > 1 and (top.score - matches[1].score) < self._ambiguity_margin:
            return QueryIntent(
                confidence=round(top.score, 4),
                ambiguities=[item.entity.name for item in matches[:5]],
            )

        entity = ResolvedEntity(
            name=top.entity.name,
            table_name=top.entity.table_name,
            key_column=top.entity.key_column,
            display_column=top.entity.display_column,
            confidence=round(top.score, 4),
            matched_terms=list(top.matched_terms),
        )

        filters = self._resolve_filters(question, top.entity)
        filter_confidence = (
            sum(item.confidence for item in filters) / len(filters)
            if filters
            else top.score
        )

        return QueryIntent(
            entity=entity,
            filters=filters,
            confidence=round((top.score + filter_confidence) / 2, 4),
        )

    def _match_entities(self, question: str, catalog: SemanticCatalog) -> list[EntityMatch]:
        question_tokens = self._tokens(question)
        matches: list[EntityMatch] = []

        for entity in catalog.entities:
            term_tokens = set().union(
                *(self._tokens(term) for term in [entity.name, *entity.synonyms])
            )
            if not term_tokens:
                continue

            overlap = question_tokens.intersection(term_tokens)
            score = len(overlap) / max(len(term_tokens), 1)
            if score >= self._minimum_entity_score:
                matches.append(
                    EntityMatch(
                        entity=entity,
                        score=round(score, 4),
                        matched_terms=tuple(sorted(overlap)),
                    )
                )

        matches.sort(key=lambda item: (-item.score, item.entity.name))
        return matches

    def _resolve_filters(
        self,
        question: str,
        entity: EntityDefinition,
    ) -> list[ResolvedFilter]:
        filters: list[ResolvedFilter] = []
        for attribute in entity.attributes:
            match = self._match_attribute_filter(question, attribute)
            if match:
                filters.append(match)

        if entity.display_column and not filters:
            entity_terms = [entity.name, *entity.synonyms]
            entity_pattern = "|".join(
                re.escape(term.replace("_", " ")) for term in sorted(entity_terms, key=len, reverse=True)
            )
            match = re.search(
                rf"\b(?:for|from)\s+(?:(?:{entity_pattern})\s+)?(?P<value>{_QUOTED_VALUE_RE}|{_VALUE_RE})",
                question,
                flags=re.IGNORECASE,
            )
            if match:
                value = self._clean_value(match.group("value"))
                if value:
                    filters.append(
                        ResolvedFilter(
                            attribute=entity.display_column,
                            column_name=entity.display_column,
                            operator="=",
                            value=value,
                            confidence=0.70,
                            source_text=match.group(0),
                        )
                    )

        return filters

    def _match_attribute_filter(
        self,
        question: str,
        attribute: EntityAttributeDefinition,
    ) -> Optional[ResolvedFilter]:
        for term in sorted([attribute.name, *attribute.synonyms], key=len, reverse=True):
            escaped = re.escape(term.replace("_", " "))
            operator_pattern = r"(?:is|equals|equal to|=|:)"
            pattern = rf"\b{escaped}\b\s*(?:{operator_pattern}\s*)?(?P<value>{_QUOTED_VALUE_RE}|{_VALUE_RE})"
            match = re.search(pattern, question, flags=re.IGNORECASE)
            if match:
                value = self._clean_value(match.group("value"))
                if value:
                    return ResolvedFilter(
                        attribute=attribute.name,
                        column_name=attribute.column_name,
                        operator="=",
                        value=value,
                        confidence=0.90,
                        source_text=match.group(0),
                    )

            if any(
                token in {"country", "region", "state", "city", "location"}
                for token in self._tokens(term)
            ):
                in_match = re.search(
                    rf"\b(?:in|within)\s+(?P<value>{_QUOTED_VALUE_RE}|{_VALUE_RE})",
                    question,
                    flags=re.IGNORECASE,
                )
                if in_match:
                    value = self._clean_value(in_match.group("value"))
                    if value:
                        return ResolvedFilter(
                            attribute=attribute.name,
                            column_name=attribute.column_name,
                            operator="=",
                            value=value,
                            confidence=0.80,
                            source_text=in_match.group(0),
                        )

        return None

    @staticmethod
    def _clean_value(value: str) -> str:
        value = value.strip().strip(",. ")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1].strip()
        return value

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {token for token in _TOKEN_RE.findall(value.casefold()) if len(token) > 1}
