import pytest

from datapilot.application.services.analytical_sql_composition import (
    BoundPredicate, GroupedQueryClauses, compose_grouped_query,
)


def clauses(**changes):
    fields=dict(
        select=('"RegionCode" AS "dimension"', 'SUM("Amount") AS "value"'),
        source='"Sales"."OrderDetail"',
        group_by=('"RegionCode"',),
        order_by=('"value" DESC',),
        limit=5,
    )
    fields.update(changes)
    return GroupedQueryClauses(**fields)


def test_basic_grouped_query():
    result=compose_grouped_query(clauses())
    assert result.sql==(
        'SELECT "RegionCode" AS "dimension", SUM("Amount") AS "value" '
        'FROM "Sales"."OrderDetail" GROUP BY "RegionCode" ORDER BY "value" DESC LIMIT 5'
    )
    assert result.parameters==()


def test_where_having_order_and_parameters():
    result=compose_grouped_query(clauses(
        where=(BoundPredicate('"Status" IN (%s, %s)',("O","T")),),
        having=(BoundPredicate('SUM("Amount") > %s',(100,)),),
    ))
    assert result.sql.index("WHERE") < result.sql.index("GROUP BY")
    assert result.sql.index("GROUP BY") < result.sql.index("HAVING")
    assert result.sql.index("HAVING") < result.sql.index("ORDER BY")
    assert result.sql.index("ORDER BY") < result.sql.index("LIMIT")
    assert result.parameters==("O","T",100)


def test_multiple_predicates_preserve_parameter_order():
    result=compose_grouped_query(clauses(
        where=(BoundPredicate('"A" = %s',("x",)),BoundPredicate('"B" = %s',("y",))),
        having=(BoundPredicate('SUM("Amount") > %s',(10,)),
                BoundPredicate('SUM("Amount") < %s',(20,))),
    ))
    assert '("A" = %s) AND ("B" = %s)' in result.sql
    assert '(SUM("Amount") > %s) AND (SUM("Amount") < %s)' in result.sql
    assert result.parameters==("x","y",10,20)


def test_no_optional_clauses():
    result=compose_grouped_query(clauses(order_by=(),limit=None))
    assert " WHERE " not in result.sql
    assert " HAVING " not in result.sql
    assert " ORDER BY " not in result.sql
    assert " LIMIT " not in result.sql


def test_values_are_not_interpolated():
    payload="x' OR TRUE --"
    result=compose_grouped_query(clauses(where=(BoundPredicate('"A" = %s',(payload,)),)))
    assert payload not in result.sql
    assert result.parameters==(payload,)


@pytest.mark.parametrize("limit",[0,-1,True,1.5,"5"])
def test_invalid_limit_rejected(limit):
    with pytest.raises(ValueError,match="LIMIT"):
        clauses(limit=limit)


def test_missing_grouping_rejected():
    with pytest.raises(ValueError,match="GROUP BY"):
        clauses(group_by=())


def test_empty_select_rejected():
    with pytest.raises(ValueError,match="SELECT"):
        clauses(select=())


def test_invalid_predicate_rejected():
    with pytest.raises(ValueError,match="predicate"):
        clauses(where=(BoundPredicate("",()),))


def test_invalid_source_rejected():
    with pytest.raises(ValueError,match="FROM"):
        clauses(source="")


def test_compiler_owned_fragments_must_be_nonempty():
    with pytest.raises(ValueError,match="fragments"):
        clauses(order_by=("",))
