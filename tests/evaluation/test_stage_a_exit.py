"""Stage A exit-gate evidence.

These tests intentionally inspect the versioned regression corpus. They prevent the
Stage A quality gate from silently losing required coverage as cases evolve.
"""

from __future__ import annotations

import json
from pathlib import Path


EVALUATION_DIR = Path(__file__).parent
SEMANTIC_CASES = EVALUATION_DIR / "semantic_cases.json"
FIXTURE_PIPELINE = EVALUATION_DIR / "test_semantic_fixture_pipeline.py"
METADATA_FIXTURE = EVALUATION_DIR / "test_semantic_metadata_fixture.py"
CORRECTNESS_TESTS = (
    EVALUATION_DIR.parent
    / "unit"
    / "application"
    / "services"
    / "test_query_correctness.py"
)


def _semantic_cases() -> list[dict]:
    return json.loads(SEMANTIC_CASES.read_text(encoding="utf-8"))


def test_stage_a_live_corpus_has_broad_semantic_composition_coverage():
    cases = _semantic_cases()
    expectations = [case.get("expected", {}) for case in cases]

    assert len(cases) >= 35
    assert any(len(expected.get("metrics", [])) >= 2 for expected in expectations)
    assert any(expected.get("relationships") for expected in expectations)
    assert any("filter_alignment" in expected.get("required_correctness_codes", []) for expected in expectations)
    assert any("grouping_dimension_alignment" in expected.get("required_correctness_codes", []) for expected in expectations)
    assert any(case.get("conversation_id") for case in cases)


def test_stage_a_exit_gate_preserves_clarification_unsupported_and_followup_coverage():
    fixture_pipeline = FIXTURE_PIPELINE.read_text(encoding="utf-8")
    cases = _semantic_cases()

    assert "entity_ambiguity_uses_real_orchestrator" in fixture_pipeline
    assert "stops_before_sql_for_non_executable_semantics" in fixture_pipeline
    assert "clarification_resumes_real_orchestrator" in fixture_pipeline

    conversations: dict[str, int] = {}
    for case in cases:
        conversation_id = case.get("conversation_id")
        if conversation_id:
            conversations[conversation_id] = conversations.get(conversation_id, 0) + 1
    assert any(turns >= 2 for turns in conversations.values())


def test_stage_a_exit_gate_preserves_time_join_and_fanout_negative_coverage():
    metadata_fixture = METADATA_FIXTURE.read_text(encoding="utf-8")
    correctness = CORRECTNESS_TESTS.read_text(encoding="utf-8")

    assert "resolves_month_over_month_comparison" in metadata_fixture
    assert "resolves_year_over_year_comparison" in metadata_fixture
    assert "fails_evaluation_harness_on_wrong_grain" in metadata_fixture
    assert "fails_harness_when_period_split_is_lost" in metadata_fixture

    assert "rejects_wrong_governed_relationship_join_columns" in correctness
    assert "rejects_partial_cross_entity_relationship_path" in correctness
    assert "rejects_sum_metric_on_one_side_joining_many_side" in correctness
    assert "allows_count_distinct_on_one_side_across_many_join" in correctness
