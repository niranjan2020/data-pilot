"""Semantic intent must be independent of the SQL proposal and its mutations."""
from datapilot.application.services.semantic_intent_contract import SemanticIntentContract


def test_contract_contains_all_governed_requirements():
    context = {
        "metrics": [{"name": "revenue", "expression": "SUM(amount)"}],
        "resolved_attribute_selection": {"column_name": "status"},
    }
    contract = SemanticIntentContract.from_governed_context(
        context,
        grouping_columns=["region"],
        required_filters=[{"column_name": "status", "operator": "=", "value": "active"}],
        required_relationships=[{"from_column": "order_id", "to_column": "id"}],
        time_plan={"grain": "month"},
    )
    result = contract.as_dict()
    assert result["metrics"][0]["name"] == "revenue"
    assert result["dimensions"] == ["region"]
    assert result["filters"][0]["value"] == "active"
    assert result["relationships"][0]["from_column"] == "order_id"
    assert result["time_plan"] == {"grain": "month"}
    assert result["categorical_attribute"] == {"column_name": "status"}


def test_contract_isolated_from_mutated_original_context():
    metrics = [{"name": "units"}]
    filters = [{"column_name": "status", "value": "active"}]
    contract = SemanticIntentContract.from_governed_context(
        {"metrics": metrics}, grouping_columns=["region"],
        required_filters=filters, required_relationships=[], time_plan=None,
    )
    metrics[0]["name"] = "incorrect"
    filters[0]["value"] = "inactive"
    assert contract.as_dict()["metrics"][0]["name"] == "units"
    assert contract.as_dict()["filters"][0]["value"] == "active"


def test_contract_export_cannot_modify_later_validation_requirements():
    contract = SemanticIntentContract.from_governed_context(
        {"metrics": [{"name": "revenue"}]},
        grouping_columns=["region"],
        required_filters=[{"column_name": "status", "value": "active"}],
        required_relationships=[], time_plan=None,
    )
    exported = contract.as_dict()
    exported["filters"][0]["value"] = "inactive"
    exported["metrics"][0]["name"] = "wrong"
    assert contract.as_dict()["filters"][0]["value"] == "active"
    assert contract.as_dict()["metrics"][0]["name"] == "revenue"


def test_empty_contract_has_predictable_json_safe_shape():
    contract = SemanticIntentContract.from_governed_context(
        {}, grouping_columns=[], required_filters=[],
        required_relationships=[], time_plan=None,
    )
    assert contract.as_dict() == {
        "metrics": [], "dimensions": [], "filters": [],
        "relationships": [], "time_plan": None, "categorical_attribute": None,
        "comparison_cohorts": [], "aggregation_grain": [],
    }


def test_comparison_cohorts_and_grain_are_independent_of_sql():
    cohorts = [{"column_name": "status", "values": ["A", "B"]}]
    contract = SemanticIntentContract.from_governed_context(
        {}, grouping_columns=["region"], required_filters=[],
        required_relationships=[], time_plan=None,
        comparison_cohorts=cohorts, aggregation_grain=["status", "region"],
    )
    cohorts[0]["values"].append("C")
    assert contract.as_dict()["comparison_cohorts"] == [
        {"column_name": "status", "values": ["A", "B"]}
    ]
    assert contract.as_dict()["aggregation_grain"] == ["status", "region"]


def test_published_comparison_cohorts_are_resolved_without_sql():
    from datapilot.application.services.semantic_intent_contract import resolve_published_comparison_cohorts
    entities = [{"attributes": [{
        "column_name": "status",
        "value_mappings": [
            {"canonical_value": "O", "synonyms": ["owned"]},
            {"canonical_value": "T", "synonyms": ["chartered"]},
        ],
    }]}]
    assert resolve_published_comparison_cohorts(
        "Compare owned versus chartered", entities,
    ) == [{"column_name": "status", "values": ["O", "T"]}]


def test_non_comparison_does_not_invent_cohorts():
    from datapilot.application.services.semantic_intent_contract import resolve_published_comparison_cohorts
    entities = [{"attributes": [{
        "column_name": "status",
        "value_mappings": [
            {"canonical_value": "O", "synonyms": ["owned"]},
            {"canonical_value": "T", "synonyms": ["chartered"]},
        ],
    }]}]
    assert resolve_published_comparison_cohorts(
        "Show owned and chartered combined total", entities,
    ) == []
