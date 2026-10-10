"""Conservative, metadata-driven categorical phrase resolution.

Only published semantic values supplied by the caller are eligible. This
module does not grant database access or infer categories from schema names.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


def _tokens(value: str) -> list[str]:
    return re.findall(r"[\w]+", str(value or "").casefold(), flags=re.UNICODE)


def _matches(tokens: list[str], phrase: list[str]) -> list[int]:
    if not phrase:
        return []
    return [
        index for index in range(len(tokens) - len(phrase) + 1)
        if tokens[index:index + len(phrase)] == phrase
    ]


def resolve_categorical_intent(
    question: str,
    published_mappings: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find explicit category mentions without treating connectors as codes.

    Expected mapping: column_name, value, and optional synonyms (strings).
    Publication is enforced by the caller supplying only published mappings.
    Ambiguous phrases resolving to different columns/values are not selected.
    """
    tokens = _tokens(question)
    candidates: list[dict[str, Any]] = []
    for mapping in published_mappings:
        column = str(mapping.get("column_name") or "").strip()
        value = str(mapping.get("value") or "").strip()
        if not column or not value:
            continue
        aliases = mapping.get("synonyms") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        for phrase in [value, *aliases]:
            words = _tokens(phrase)
            for index in _matches(tokens, words):
                # Single-token category codes that are ordinary connective
                # words must be explicitly quoted or handled by a richer
                # semantic intent plan. Avoid substring matching altogether.
                if len(words) == 1 and words[0] in {
                    "to", "in", "on", "at", "by", "as", "or", "and", "for",
                    "of", "from", "with",
                }:
                    if not re.search(
                        r"(?<!\w)[\x27\x22\u2018\u2019\u201c\u201d]"
                        + re.escape(str(phrase).strip())
                        + r"[\x27\x22\u2018\u2019\u201c\u201d](?!\w)",
                        question,
                        flags=re.I,
                    ):
                        continue
                candidates.append({
                    "column_name": column,
                    "value": value,
                    "phrase": str(phrase),
                    "token_start": index,
                    "token_count": len(words),
                })
    # Longest phrase wins at the same token span; tied distinct mappings are
    # ambiguous and deliberately excluded.
    winners: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda c: -c["token_count"]):
        span = set(range(candidate["token_start"], candidate["token_start"] + candidate["token_count"]))
        if any(span & set(range(w["token_start"], w["token_start"] + w["token_count"])) for w in winners):
            continue
        tied = [
            c for c in candidates
            if c["token_start"] == candidate["token_start"]
            and c["token_count"] == candidate["token_count"]
        ]
        if len({(c["column_name"].casefold(), c["value"].casefold()) for c in tied}) > 1:
            continue
        winners.append(candidate)
    return [
        {"column_name": item["column_name"], "value": item["value"],
         "matched_phrase": item["phrase"]}
        for item in sorted(winners, key=lambda c: c["token_start"])
    ]
