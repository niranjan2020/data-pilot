import pytest

from datapilot.application.services.query_correctness import assess_query_correctness
from datapilot.application.services.ranking_grain_repair import repair_ranking_grain


@pytest.mark.parametrize("entity,filter_column,filter_values", [
    ("operator", "ownership_status", "('O', 'T')"),
    ("customer", "status", "('paid', 'pending')"),
    ("product", "color", "('red', 'blue')"),
    ("supplier", "category", "('A', 'B')"),
])
def test_top_n_filter_dimension_not_ranking_grain(entity, filter_column, filter_values):
    sql = (
        f"SELECT {entity}, {filter_column}, COUNT(DISTINCT id) AS n "
        f"FROM records WHERE {filter_column} IN {filter_values} "
        f"GROUP BY {entity}, {filter_column} ORDER BY n DESC LIMIT 10"
    )
    question = f"Show top 10 {entity}s by distinct count filtered to selected {filter_column}"
    checks = assess_query_correctness(
        affected_tables=["records"], governed_tables=["records"], sql=sql,
        question=question, required_grouping_columns=[entity],
    )
    assert any(c["code"] == "ranking_grain_violation" and c["status"] == "failed" for c in checks)
    repaired = repair_ranking_grain(sql, checks)
    assert repaired is not None
    assert f"GROUP BY {entity}" in repaired
    assert f"{filter_column} IN" in repaired
    assert f"GROUP BY {entity}, {filter_column}" not in repaired
    after = assess_query_correctness(
        affected_tables=["records"], governed_tables=["records"], sql=repaired,
        question=question, required_grouping_columns=[entity],
    )
    assert not any(c["status"] == "failed" for c in after)


def test_no_repair_without_authoritative_grouping():
    sql = "SELECT customer, status, COUNT(*) AS n FROM records GROUP BY customer, status ORDER BY n DESC LIMIT 10"
    checks = assess_query_correctness(
        affected_tables=["records"], governed_tables=["records"], sql=sql,
        question="top 10 customers", required_grouping_columns=[],
    )
    assert repair_ranking_grain(sql, checks) is None


def test_no_repair_when_extra_column_used_in_ordering():
    sql = "SELECT customer, status, COUNT(*) AS n FROM records GROUP BY customer, status ORDER BY status LIMIT 10"
    checks = assess_query_correctness(
        affected_tables=["records"], governed_tables=["records"], sql=sql,
        question="top 10 customers", required_grouping_columns=["customer"],
    )
    assert repair_ranking_grain(sql, checks) is None


def test_explicit_breakdown_not_rejected():
    sql = "SELECT customer, status, COUNT(*) AS n FROM records GROUP BY customer, status ORDER BY n DESC LIMIT 10"
    checks = assess_query_correctness(
        affected_tables=["records"], governed_tables=["records"], sql=sql,
        question="top 10 customers grouped by status", required_grouping_columns=["customer"],
    )
    assert not any(c["code"] == "ranking_grain_violation" for c in checks)


from datapilot.application.services.query_orchestrator import QueryOrchestrator


@pytest.mark.parametrize("entity,column,filter_column", [
    ("operator", "operator", "ownership_status"),
    ("customer", "customer_name", "payment_status"),
    ("product", "product_name", "color"),
    ("supplier", "supplier_name", "category"),
])
def test_ranked_entity_grain_excludes_filter_only_dimension(entity, column, filter_column):
    question = f"Show the top 10 {entity}s by distinct count with {filter_column} selected"
    entities = [{"name": entity, "display_column": column,
                 "attributes": [{"name": filter_column, "column_name": filter_column}]}]
    resolved = QueryOrchestrator._required_grouping_columns(
        question, entities, metrics=[]
    )
    assert resolved == [column]


@pytest.mark.parametrize("question", [
    "Show top 10 products by product colour",
    "Show top 10 products by colour",
])
def test_top_n_explicit_dimension_overrides_ranked_entity(question):
    entities = [{"name": "Product", "display_column": "Name",
                 "attributes": [{"name": "Color", "column_name": "Color",
                                 "synonyms": ["colour", "product colour"]}]}]
    assert QueryOrchestrator._required_grouping_columns(question, entities, metrics=[]) == ["Color"]


def test_top_n_metric_preserves_ranked_entity():
    entities = [{"name": "Product", "display_column": "Name",
                 "attributes": [{"name": "Color", "column_name": "Color",
                                 "synonyms": ["colour"]}]}]
    assert QueryOrchestrator._required_grouping_columns(
        "Show top 10 products by distinct sales count filtered to red colour",
        entities, metrics=[]
    ) == ["Name"]


def test_top_n_filter_selection_does_not_override_ranked_entity():
    entities = [{"name": "Operator", "synonyms": ["operators"],
                 "display_column": "operator",
                 "attributes": [{"name": "Ownership status", "column_name": "ownership_status"}]}]
    question = ("Show the top 10 operators by distinct vessel count for vessels built "
                "after 2015, in the container segment, with ownership status owned or time-chartered.")
    assert QueryOrchestrator._required_grouping_columns(
        question, entities, selected_attribute={"column_name": "ownership_status"},
        metrics=[],
    ) == ["operator"]


def test_top_n_explicit_dimension_with_selected_attribute():
    entities = [{"name": "Product", "display_column": "Name",
                 "attributes": [{"name": "Color", "column_name": "Color",
                                 "synonyms": ["colour"]}]}]
    assert QueryOrchestrator._required_grouping_columns(
        "Show top 10 products by product colour", entities,
        selected_attribute={"column_name": "Color"}, metrics=[],
    ) == ["Color"]


def test_top_n_ranked_attribute_does_not_take_filter_attribute_as_grouping():
    entities = [{"name": "Vessel", "display_column": "vessel_name",
                 "attributes": [
                     {"name": "Operator", "column_name": "operator", "synonyms": ["operators"]},
                     {"name": "Ownership Status", "column_name": "ownership_status",
                      "synonyms": ["ownership"]},
                     {"name": "Vessel Segment", "column_name": "vessel_segment"},
                 ]}]
    question = ("Show the top 10 operators by distinct vessel count for vessels built after 2015, "
                "in the container segment, with ownership status owned or time-chartered.")
    assert QueryOrchestrator._required_grouping_columns(
        question, entities, selected_attribute={"column_name": "ownership_status"}, metrics=[]
    ) == ["operator"]


def test_top_n_unknown_ranked_entity_does_not_infer_grain_from_filter():
    entities = [{"name": "Vessel", "display_column": "vessel_name",
                 "attributes": [{"name": "Ownership Status", "column_name": "ownership_status"}]}]
    assert QueryOrchestrator._required_grouping_columns(
        "Show top 10 operators by vessel count with ownership status owned",
        entities, selected_attribute={"column_name": "ownership_status"}, metrics=[]
    ) == []


@pytest.mark.parametrize("question", [
    "Show top 10 managing owners by vessel count",
    "Show the top 5 managing owners by distinct vessel count with LNG fuel",
])
def test_maritime_ranked_attribute_uses_managing_owner_grain(question):
    entities = [{
        "name": "Vessel",
        "display_column": "vessel_name",
        "attributes": [
            {"name": "Managing Owner", "column_name": "managing_owner",
             "synonyms": ["managing owners"]},
            {"name": "Alternative Fuel Type", "column_name": "alternative_fuel_type",
             "synonyms": ["fuel"]},
        ],
    }]
    assert QueryOrchestrator._required_grouping_columns(
        question, entities,
        selected_attribute={"column_name": "alternative_fuel_type"},
        metrics=[],
    ) == ["managing_owner"]


def test_maritime_ranking_rejects_fuel_grouping_instead_of_owner():
    from datapilot.application.services.query_correctness import assess_query_correctness

    checks = assess_query_correctness(
        affected_tables=["public.vessels"],
        governed_tables=["public.vessels"],
        sql=(
            "SELECT alternative_fuel_type, COUNT(*) AS vessel_count "
            "FROM public.vessels GROUP BY alternative_fuel_type "
            "ORDER BY vessel_count DESC LIMIT 10"
        ),
        question="Show top 10 managing owners by vessel count",
        required_grouping_columns=["managing_owner"],
    )
    assert any(
        c["status"] == "failed"
        and c["code"] in {"grouping_dimension_violation", "ranking_grain_violation"}
        for c in checks
    )
