"""Deterministic semantic matching services."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List

from datapilot.domain.semantic import QueryTemplate, SemanticCatalog


_TOKEN_RE = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True)
class TemplateMatch:
    """Candidate template and deterministic match evidence."""

    template: QueryTemplate
    score: float
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class TemplateMatchResult:
    """Template matching result with explicit ambiguity information."""

    matches: tuple[TemplateMatch, ...]
    is_ambiguous: bool
    confidence: float


class SemanticMatcher:
    """Match questions to semantic templates without calling an LLM."""

    def match_templates(
        self,
        question: str,
        catalog: SemanticCatalog,
        *,
        ambiguity_margin: float = 0.10,
        minimum_score: float = 0.20,
    ) -> TemplateMatchResult:
        question_tokens = self._tokens(question)
        candidates: List[TemplateMatch] = []

        for template in catalog.templates:
            if not template.enabled:
                continue

            terms = {
                self._normalize_term(template.name),
                *[self._normalize_term(value) for value in template.synonyms],
            }
            term_tokens = set().union(*(self._tokens(term) for term in terms))
            if not term_tokens:
                continue

            overlap = question_tokens.intersection(term_tokens)
            score = len(overlap) / max(len(term_tokens), 1)
            if score >= minimum_score:
                candidates.append(
                    TemplateMatch(
                        template=template,
                        score=round(score, 4),
                        matched_terms=tuple(sorted(overlap)),
                    )
                )

        candidates.sort(key=lambda item: (-item.score, item.template.priority, item.template.name))

        if not candidates:
            return TemplateMatchResult(matches=(), is_ambiguous=False, confidence=0.0)

        top = candidates[0]
        confidence = top.score
        ambiguous = (
            len(candidates) > 1
            and (top.score - candidates[1].score) < ambiguity_margin
        )

        return TemplateMatchResult(
            matches=tuple(candidates),
            is_ambiguous=ambiguous,
            confidence=round(confidence, 4),
        )

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {
            token
            for token in _TOKEN_RE.findall(value.casefold())
            if len(token) > 1
        }

    @staticmethod
    def _normalize_term(value: str) -> str:
        return " ".join(value.casefold().replace("_", " ").split())
