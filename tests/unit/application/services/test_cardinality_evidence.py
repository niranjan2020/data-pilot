"""Regression coverage for conservative cardinality evidence summaries."""

import pytest

from datapilot.application.services.cardinality_evidence import (
    REQUIRED_SIGNALS,
    summarize_cardinality_evidence,
)


@pytest.mark.parametrize("missing", REQUIRED_SIGNALS)
def test_each_missing_signal_prevents_complete_evidence(missing):
    signals = {name: True for name in REQUIRED_SIGNALS}
    signals[missing] = False
    result = summarize_cardinality_evidence(signals, metric="revenue", relationship="orders")
    assert result["code"] == "fanout_cardinality_evidence_incomplete"
    assert result["missing_evidence"] == [missing]
    assert result["join_cardinality_safe"] is False


@pytest.mark.parametrize("value", [False, None, 0, 1, "true", "yes", [], {}, object()])
def test_non_boolean_evidence_never_counts_as_verified(value):
    signals = {name: True for name in REQUIRED_SIGNALS}
    signals["metric_ownership"] = value
    result = summarize_cardinality_evidence(signals)
    assert result["missing_evidence"] == ["metric_ownership"]
    assert result["join_cardinality_safe"] is False


@pytest.mark.parametrize("missing_count", range(1, len(REQUIRED_SIGNALS) + 1))
def test_multiple_missing_signals_are_reported_in_stable_order(missing_count):
    signals = {name: True for name in REQUIRED_SIGNALS}
    for name in REQUIRED_SIGNALS[:missing_count]:
        signals[name] = False
    result = summarize_cardinality_evidence(signals)
    assert result["missing_evidence"] == list(REQUIRED_SIGNALS[:missing_count])
    assert result["status"] == "skipped"


@pytest.mark.parametrize("metric,relationship", [
    ("revenue", "orders"), ("count", None), ("", ""), ("amount", "parent_children"),
])
def test_evidence_preserves_diagnostic_context(metric, relationship):
    result = summarize_cardinality_evidence(
        {name: True for name in REQUIRED_SIGNALS},
        metric=metric,
        relationship=relationship,
    )
    assert result["metric"] == metric
    assert result["relationship"] == relationship
    assert result["code"] == "fanout_cardinality_evidence_complete"
    assert result["join_cardinality_safe"] is False


def test_complete_evidence_is_not_a_cardinality_safety_waiver():
    result = summarize_cardinality_evidence({name: True for name in REQUIRED_SIGNALS})
    assert result["status"] == "passed"
    assert result["missing_evidence"] == []
    assert result["join_cardinality_safe"] is False


def test_missing_evidence_defaults_to_unverified():
    result = summarize_cardinality_evidence({})
    assert result["missing_evidence"] == list(REQUIRED_SIGNALS)
    assert result["join_cardinality_safe"] is False


def test_unknown_signals_cannot_override_required_evidence():
    result = summarize_cardinality_evidence({"approved": True, "safe": True})
    assert result["code"] == "fanout_cardinality_evidence_incomplete"
    assert result["join_cardinality_safe"] is False
