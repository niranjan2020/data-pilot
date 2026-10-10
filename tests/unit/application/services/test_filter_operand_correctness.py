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


@pytest.mark.parametrize("operator,predicate,expected", [
    (">", "10 < age", "passed"),
    (">=", "10 <= age", "passed"),
    ("<", "10 > age", "passed"),
    ("<=", "10 >= age", "passed"),
    ("!=", "'inactive' != status", "passed"),
    ("<>", "'inactive' <> status", "passed"),
    (">", "10 > age", "failed"),
    (">=", "10 >= age", "failed"),
    ("<", "10 < age", "failed"),
    ("<=", "10 <= age", "failed"),
    (">", "age < 10", "failed"),
    ("<", "age > 10", "failed"),
])
def test_reversed_comparison_preserves_direction(operator, predicate, expected):
    result = assess_query_correctness(
        affected_tables=["public.records"],
        governed_tables=["public.records"],
        sql="SELECT * FROM public.records WHERE " + predicate,
        required_filters=[{
            "column_name": "status" if operator in ("!=", "<>") else "age",
            "operator": operator,
            "value": "inactive" if operator in ("!=", "<>") else "10",
        }],
    )
    filter_results = [c for c in result if c["code"] in ("filter_alignment", "filter_violation")]
    assert len(filter_results) == 1
    assert filter_results[0]["status"] == expected


@pytest.mark.parametrize("predicate", [
    "10 < COALESCE(age, 0)",
    "10 < age OR region = 'north'",
    "NOT (10 < age)",
])
def test_reversed_comparison_cannot_be_hidden_in_expression_or_or(predicate):
    result = assess_query_correctness(
        affected_tables=["public.records"],
        governed_tables=["public.records"],
        sql="SELECT * FROM public.records WHERE " + predicate,
        required_filters=[{"column_name": "age", "operator": ">", "value": "10"}],
    )
    assert any(c["code"] == "filter_violation" for c in result)


@pytest.mark.parametrize("predicate,expected,status", [
    ("status = 'O'", "O", "passed"),
    ("status = 'o'", "O", "failed"),
    ("LOWER(status) = 'o'", "O", "passed"),
    ("LOWER(status) = 'O'", "O", "failed"),
    ("LOWER(status) = 'active'", "active", "passed"),
    ("LOWER(status) = 'ACTIVE'", "active", "failed"),
    ("status = 'Active'", "active", "failed"),
    ("status = 'active'", "active", "passed"),
])
def test_canonical_filter_value_respects_sql_case_semantics(predicate, expected, status):
    result = assess_query_correctness(
        affected_tables=["public.records"],
        governed_tables=["public.records"],
        sql="SELECT * FROM public.records WHERE " + predicate,
        required_filters=[{
            "column_name": "status",
            "operator": "=",
            "value": expected,
            "data_type": "text",
        }],
    )
    actual = [c for c in result if c["code"] in ("filter_alignment", "filter_violation")]
    assert len(actual) == 1
    assert actual[0]["status"] == status


@pytest.mark.parametrize("operator,predicate", [
    (">", "LOWER(status) > 'b'"),
    (">=", "LOWER(status) >= 'b'"),
    ("<", "LOWER(status) < 'b'"),
    ("<=", "LOWER(status) <= 'b'"),
    (">", "'b' < LOWER(status)"),
])
def test_transformed_column_does_not_satisfy_governed_range(operator, predicate):
    result = assess_query_correctness(
        affected_tables=["public.records"],
        governed_tables=["public.records"],
        sql="SELECT * FROM public.records WHERE " + predicate,
        required_filters=[{
            "column_name": "status", "operator": operator,
            "value": "b", "data_type": "text",
        }],
    )
    assert any(c["code"] == "filter_violation" for c in result)
