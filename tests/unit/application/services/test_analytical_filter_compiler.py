import pytest

from datapilot.application.services.analytical_dimensions import AnalyticalDimension
from datapilot.application.services.analytical_filter_compiler import (
    compile_governed_dimension_filter,
)


def dimensions():
    return (
        AnalyticalDimension("Ownership", 1, "Vessel", "astra", "vessel", "ownership_status"),
        AnalyticalDimension("Ownership", 2, "Contract", "astra", "contract", "ownership"),
    )


def compile(*, name="Vessel.Ownership", operator="EQ", values=("O",), approved=None, max_values=100):
    return compile_governed_dimension_filter(
        dimension_name=name, operator=operator, values=values,
        published_dimensions=dimensions() if approved is None else approved,
        max_values=max_values,
    )


def test_eq_uses_placeholder_not_literal():
    result=compile(values=("O' OR 1=1 --",))
    assert result.sql=='"ownership_status" = %s'
    assert result.parameters==("O' OR 1=1 --",)


def test_in_uses_one_placeholder_per_value():
    result=compile(operator="IN",values=("O","T","TO"))
    assert result.sql=='"ownership_status" IN (%s, %s, %s)'
    assert result.parameters==("O","T","TO")


def test_filter_carries_governed_source():
    result=compile()
    assert (result.entity_id,result.schema_name,result.table_name)==(1,"astra","vessel")


def test_unpublished_attribute_rejected():
    with pytest.raises(ValueError):
        compile(approved=())


def test_ambiguous_short_name_rejected():
    with pytest.raises(ValueError):
        compile(name="Ownership")


@pytest.mark.parametrize("operator",["LIKE","OR","eq","IS NULL"])
def test_unsupported_operator_rejected(operator):
    with pytest.raises(ValueError,match="Unsupported"):
        compile(operator=operator)


@pytest.mark.parametrize("values", [(),("O","T"),("O",None)])
def test_invalid_eq_values_rejected(values):
    with pytest.raises(ValueError):
        compile(values=values)


def test_in_count_capped():
    with pytest.raises(ValueError,match="bounded"):
        compile(operator="IN",values=("O","T"),max_values=1)


def test_invalid_limit_rejected():
    with pytest.raises(ValueError,match="limit"):
        compile(max_values=True)


def test_boolean_not_interpreted_as_sql():
    result=compile(values=(True,))
    assert result.sql.endswith("= %s")
    assert result.parameters==(True,)


def test_quoted_column_escaped():
    approved=(AnalyticalDimension("Ownership",1,"Vessel","astra","vessel",'odd"column'),)
    assert compile(approved=approved).sql=='"odd""column" = %s'


def test_nonfinite_float_rejected():
    with pytest.raises(ValueError,match="Non-finite"):
        compile(values=(float("nan"),))


def test_value_length_capped():
    with pytest.raises(ValueError,match="size limit"):
        compile(values=("a"*4097,))
