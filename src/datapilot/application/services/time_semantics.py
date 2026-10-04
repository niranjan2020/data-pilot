"""Deterministic interpretation of common relative calendar phrases."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _shift_month(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _quarter_start(value: date) -> date:
    month = ((value.month - 1) // 3) * 3 + 1
    return date(value.year, month, 1)


def _shift_quarter(value: date, quarters: int) -> date:
    return _shift_month(_quarter_start(value), quarters * 3)


def resolve_time_semantics(
    question: str,
    time_dimensions: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Resolve one governed time role and a half-open date range.

    The resolver intentionally handles only unambiguous calendar phrases. Unknown
    temporal language is left to later capabilities rather than guessed.
    """
    if not time_dimensions:
        return None
    q = " " + re.sub(r"[^a-z0-9]+", " ", question.lower()).strip() + " "

    explicit = []
    for dimension in time_dimensions:
        terms = [dimension.get("name") or "", dimension.get("role") or "", *(dimension.get("synonyms") or [])]
        if any(
            term and f" {re.sub(r'[^a-z0-9]+', ' ', term.lower()).strip()} " in q
            for term in terms
        ):
            explicit.append(dimension)
    if len(explicit) > 1:
        return {"status": "ambiguous", "candidates": [d["name"] for d in explicit]}
    dimension = explicit[0] if explicit else next(
        (d for d in time_dimensions if d.get("is_default")), None
    )
    if dimension is None:
        return None

    timezone = dimension.get("timezone") or "UTC"
    try:
        today = (now.astimezone(ZoneInfo(timezone)).date() if now else datetime.now(ZoneInfo(timezone)).date())
    except Exception:
        timezone = "UTC"
        today = (now.astimezone(ZoneInfo("UTC")).date() if now else datetime.now(ZoneInfo("UTC")).date())

    start: date | None = None
    end: date | None = None
    phrase: str | None = None
    if " yesterday " in q:
        phrase, start, end = "yesterday", today - timedelta(days=1), today
    elif " today " in q:
        phrase, start, end = "today", today, today + timedelta(days=1)
    elif " last month " in q or " previous month " in q:
        phrase, end = "last month", _month_start(today)
        start = _shift_month(end, -1)
    elif " this month " in q:
        phrase, start = "this month", _month_start(today)
        end = _shift_month(start, 1)
    elif " last quarter " in q or " previous quarter " in q:
        phrase, end = "last quarter", _quarter_start(today)
        start = _shift_quarter(end, -1)
    elif " this quarter " in q:
        phrase, start = "this quarter", _quarter_start(today)
        end = _shift_quarter(start, 1)
    elif " last year " in q or " previous year " in q:
        phrase = "last year"
        start, end = date(today.year - 1, 1, 1), date(today.year, 1, 1)
    elif " this year " in q:
        phrase = "this year"
        start, end = date(today.year, 1, 1), date(today.year + 1, 1, 1)
    elif " ytd " in q or " year to date " in q:
        phrase = "YTD"
        start, end = date(today.year, 1, 1), today + timedelta(days=1)
    else:
        match = re.search(r"\b(?:last|past)\s+(\d+)\s+days?\b", q)
        if match:
            days = max(1, int(match.group(1)))
            phrase = f"last {days} days"
            start, end = today - timedelta(days=days - 1), today + timedelta(days=1)

    if start is None or end is None:
        return None
    return {
        "status": "resolved",
        "phrase": phrase,
        "time_dimension": dimension["name"],
        "entity": dimension["entity_name"],
        "schema_name": dimension["schema_name"],
        "table_name": dimension["table_name"],
        "column_name": dimension["column_name"],
        "role": dimension.get("role") or "event_time",
        "grain": dimension.get("grain") or "day",
        "timezone": timezone,
        "start": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "predicate_semantics": "column >= start AND column < end_exclusive",
    }
