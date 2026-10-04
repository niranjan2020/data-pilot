from datetime import datetime
from zoneinfo import ZoneInfo

from datapilot.application.services.time_semantics import resolve_time_semantics


def _dimensions():
    return [{
        "id": 1,
        "name": "Order Date",
        "entity_id": 10,
        "entity_name": "Sales Order",
        "schema_name": "Sales",
        "table_name": "SalesOrderHeader",
        "column_name": "OrderDate",
        "role": "order_date",
        "grain": "day",
        "timezone": "UTC",
        "is_default": True,
        "synonyms": ["ordered", "sale date"],
    }]


NOW = datetime(2026, 10, 4, 12, 0, tzinfo=ZoneInfo("UTC"))


def test_resolves_last_month_as_half_open_range():
    result = resolve_time_semantics("show revenue last month", _dimensions(), now=NOW)
    assert result["start"] == "2026-09-01"
    assert result["end_exclusive"] == "2026-10-01"
    assert result["column_name"] == "OrderDate"


def test_resolves_ytd():
    result = resolve_time_semantics("show YTD revenue", _dimensions(), now=NOW)
    assert result["start"] == "2026-01-01"
    assert result["end_exclusive"] == "2026-10-05"


def test_resolves_last_n_days():
    result = resolve_time_semantics("orders for the last 30 days", _dimensions(), now=NOW)
    assert result["start"] == "2026-09-05"
    assert result["end_exclusive"] == "2026-10-05"


def test_does_not_invent_time_filter_without_temporal_phrase():
    assert resolve_time_semantics("show revenue by product", _dimensions(), now=NOW) is None


def test_requires_default_when_role_is_not_explicit():
    dimensions = [{**_dimensions()[0], "is_default": False}]
    assert resolve_time_semantics("show revenue last month", dimensions, now=NOW) is None


def test_explicit_role_can_select_non_default_dimension():
    dimensions = [
        {**_dimensions()[0], "name": "Order Date", "is_default": True},
        {**_dimensions()[0], "id": 2, "name": "Ship Date", "column_name": "ShipDate",
         "role": "ship_date", "is_default": False, "synonyms": ["shipped"]},
    ]
    result = resolve_time_semantics("show orders shipped last month", dimensions, now=NOW)
    assert result["time_dimension"] == "Ship Date"
    assert result["column_name"] == "ShipDate"
