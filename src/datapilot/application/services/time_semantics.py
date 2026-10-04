"""Deterministic interpretation of governed calendar filters, grains and comparisons."""

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


def _period(label: str, start: date, end: date) -> dict[str, str]:
    return {"label": label, "start": start.isoformat(), "end_exclusive": end.isoformat()}


def _select_dimension(question: str, dimensions: list[dict[str, Any]]) -> dict[str, Any] | None:
    q = " " + re.sub(r"[^a-z0-9]+", " ", question.lower()).strip() + " "
    explicit: list[dict[str, Any]] = []
    for dimension in dimensions:
        terms = [dimension.get("name") or "", dimension.get("role") or "", *(dimension.get("synonyms") or [])]
        if any(
            term and f" {re.sub(r'[^a-z0-9]+', ' ', term.lower()).strip()} " in q
            for term in terms
        ):
            explicit.append(dimension)
    if len(explicit) > 1:
        return {"_ambiguous": True, "candidates": [d["name"] for d in explicit]}
    return explicit[0] if explicit else next((d for d in dimensions if d.get("is_default")), None)


def _grouping_grain(question: str) -> str | None:
    q = question.lower()
    patterns = (
        ("day", r"\b(?:daily|by\s+day|per\s+day)\b"),
        ("week", r"\b(?:weekly|by\s+week|per\s+week)\b"),
        ("month", r"\b(?:monthly|by\s+month|per\s+month)\b"),
        ("quarter", r"\b(?:quarterly|by\s+quarter|per\s+quarter)\b"),
        ("year", r"\b(?:yearly|annually|by\s+year|per\s+year)\b"),
    )
    for grain, pattern in patterns:
        if re.search(pattern, q):
            return grain
    if re.search(r"\btrend\b", q):
        return "month"
    return None


def resolve_time_semantics(
    question: str,
    time_dimensions: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Resolve governed time role, calendar range, grouping grain and comparisons.

    Ranges are half-open. Only explicit, deterministic phrases are resolved; the
    SQL-generation model is not allowed to reinterpret a resolved time plan.
    """
    if not time_dimensions:
        return None
    dimension = _select_dimension(question, time_dimensions)
    if dimension is None:
        return None
    if dimension.get("_ambiguous"):
        return {"status": "ambiguous", "candidates": dimension["candidates"]}

    timezone = dimension.get("timezone") or "UTC"
    try:
        zone = ZoneInfo(timezone)
    except Exception:
        timezone, zone = "UTC", ZoneInfo("UTC")
    today = now.astimezone(zone).date() if now else datetime.now(zone).date()
    q = " " + re.sub(r"[^a-z0-9]+", " ", question.lower()).strip() + " "
    grouping = _grouping_grain(question)

    base = {
        "status": "resolved",
        "time_dimension": dimension["name"],
        "entity": dimension["entity_name"],
        "schema_name": dimension["schema_name"],
        "table_name": dimension["table_name"],
        "column_name": dimension["column_name"],
        "role": dimension.get("role") or "event_time",
        "source_grain": dimension.get("grain") or "day",
        "timezone": timezone,
        "grouping_grain": grouping,
        "grouping_semantics": (
            f"Group the governed time column by {grouping}" if grouping else None
        ),
    }

    # Explicit comparison is a first-class plan, not two competing filters.
    if (
        (" this month " in q and (" last month " in q or " previous month " in q))
        or re.search(r"\bcompare\b.*\bmonth\b", q)
        and " this month " in q
    ):
        current_start = _month_start(today)
        previous_start = _shift_month(current_start, -1)
        return {
            **base,
            "phrase": "this month vs last month",
            "comparison": True,
            "periods": [
                _period("this month", current_start, _shift_month(current_start, 1)),
                _period("last month", previous_start, current_start),
            ],
            "comparison_semantics": "Compute the requested metric separately for each governed period.",
        }
    if (
        (" this year " in q and (" last year " in q or " previous year " in q))
        or (" ytd " in q and (" last year " in q or " previous year " in q))
    ):
        current_start = date(today.year, 1, 1)
        if " ytd " in q:
            prior_end = date(today.year - 1, today.month, today.day) + timedelta(days=1)
            current_end = today + timedelta(days=1)
            phrase = "YTD vs prior-year YTD"
        else:
            prior_end = current_start
            current_end = date(today.year + 1, 1, 1)
            phrase = "this year vs last year"
        return {
            **base,
            "phrase": phrase,
            "comparison": True,
            "periods": [
                _period("current period", current_start, current_end),
                _period("prior-year period", date(today.year - 1, 1, 1), prior_end),
            ],
            "comparison_semantics": "Compute the requested metric separately for each governed period.",
        }

    start: date | None = None
    end: date | None = None
    phrase: str | None = None

    rolling_months = re.search(r"\b(?:last|past)\s+(\d+)\s+months?\b", q)
    rolling_days = re.search(r"\b(?:last|past)\s+(\d+)\s+days?\b", q)
    if rolling_months:
        months = max(1, int(rolling_months.group(1)))
        phrase = f"last {months} months"
        end = today + timedelta(days=1)
        start = _shift_month(_month_start(today), -(months - 1))
    elif " yesterday " in q:
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
    elif rolling_days:
        days = max(1, int(rolling_days.group(1)))
        phrase = f"last {days} days"
        start, end = today - timedelta(days=days - 1), today + timedelta(days=1)

    # Grouping alone (for example "orders by year") is still a governed time plan.
    if start is None or end is None:
        if grouping:
            return {
                **base,
                "phrase": f"by {grouping}",
                "comparison": False,
                "filter": None,
            }
        return None

    return {
        **base,
        "phrase": phrase,
        "comparison": False,
        "start": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "predicate_semantics": "column >= start AND column < end_exclusive",
    }
