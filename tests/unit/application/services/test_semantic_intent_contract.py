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
    }
