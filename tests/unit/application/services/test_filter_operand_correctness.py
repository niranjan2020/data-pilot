"""Independent governed filter alignment must inspect operand structure."""
import pytest
from datapilot.application.services.query_correctness import assess_query_correctness


def checks(sql, operator="=", value="active"):
    return [
        c for c in assess_query_correctness(
            affected_tables=["public.records"],
            governed_tables=["public.records"],
            sql=sql,
            required_filters=[{
                "column_name": "status",
                "operator": operator,
                "value": value,
                "data_type": "text",
            }],
        )
        if c["code"] in ("filter_alignment", "filter_violation")
    ]


@pytest.mark.parametrize("predicate", [
    "COALESCE(status, 'active') = 'active'",
    "CASE WHEN status = 'inactive' THEN 'active' ELSE 'active' END = 'active'",
    "CONCAT(status, '') = 'active'",
    "TRIM(status) = 'active'",
    "status = 'active' OR region = 'north'",
    "NOT (status = 'active')",
    "LOWER(status) = 'inactive'",
    "status = 'inactive'",
])
def test_unsafe_or_incorrect_filter_does_not_satisfy_required_equality(predicate):
    result = checks("SELECT * FROM public.records WHERE " + predicate)
    assert result and result[0]["code"] == "filter_violation"
    assert result[0]["status"] == "failed"


@pytest.mark.parametrize("predicate", [
    "status = 'active'",
    "'active' = status",
    "LOWER(status) = 'active'",
    "region = 'north' AND status = 'active'",
    "status = 'active' AND region = 'north'",
])
def test_guaranteed_governed_equality_is_accepted(predicate):
    result = checks("SELECT * FROM public.records WHERE " + predicate)
    assert result and result[0]["code"] == "filter_alignment"
    assert result[0]["status"] == "passed"


@pytest.mark.parametrize("predicate", [
    "COALESCE(status, 'active') > 'inactive'",
    "CONCAT(status, '') > 'inactive'",
])
def test_non_equality_expression_masking_is_rejected(predicate):
    result = checks("SELECT * FROM public.records WHERE " + predicate, ">", "inactive")
    assert result and result[0]["code"] == "filter_violation"
