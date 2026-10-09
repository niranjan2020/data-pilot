"""Regression coverage for composer integration into existing governed paths."""

from datapilot.application.services.analytical_sql_compiler import (
    _compose_validated_grouped_limit,
    GovernedMetricSource,
)
from datapilot.application.services.analytical_sql_composition import BoundPredicate

from test_analytical_grouped_limit_compiler import physical


def test_shared_composer_matches_legacy_grouped_sql():
    plan=physical()
    source=GovernedMetricSource(1,"Sales","OrderDetail","Amount")
    result=_compose_validated_grouped_limit(plan,source)
    assert result.sql.endswith('GROUP BY "RegionCode" ORDER BY "value" DESC LIMIT 5')
    assert result.parameters==()


def test_composer_preserves_where_then_having_parameter_order():
    plan=physical()
    source=GovernedMetricSource(1,"Sales","OrderDetail","Amount")
    result=_compose_validated_grouped_limit(
        plan,source,
        where=(BoundPredicate('"StatusCode" IN (%s, %s)',("O","TO")),),
        having=(BoundPredicate('SUM("Amount") > %s',(100,)),),
    )
    assert result.sql.index("WHERE") < result.sql.index("GROUP BY")
    assert result.sql.index("GROUP BY") < result.sql.index("HAVING")
    assert result.sql.index("HAVING") < result.sql.index("ORDER BY")
    assert result.parameters==("O","TO",100)
