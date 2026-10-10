"""Generic semantic category phrase resolution regressions."""
import pytest

from datapilot.application.services.categorical_intent import resolve_categorical_intent


MAPPINGS = [
    {"column_name": "ownership_status", "value": "O", "synonyms": ["owned"]},
    {"column_name": "ownership_status", "value": "T", "synonyms": ["time chartered"]},
    {"column_name": "ownership_status", "value": "TO", "synonyms": ["owned but chartered"]},
    {"column_name": "fuel_type", "value": "LNG", "synonyms": ["liquefied natural gas"]},
]


@pytest.mark.parametrize("question", [
    "Show records from 2015 to 2025",
    "Compare 2020 to 2026",
    "Show counts by region",
])
def test_unquoted_connective_does_not_match_category_code(question):
    assert not any(x["value"] == "TO" for x in resolve_categorical_intent(question, MAPPINGS))


@pytest.mark.parametrize("question,expected", [
    ("Show TO records", None),
    ("Show 'TO' records", "TO"),
    ("Show owned but chartered records", "TO"),
    ("Show time chartered records", "T"),
    ("Show LNG records", "LNG"),
    ("Show liquefied natural gas records", "LNG"),
])
def test_published_category_phrase_matching(question, expected):
    result = resolve_categorical_intent(question, MAPPINGS)
    assert ([x["value"] for x in result] == [expected]) if expected else result == []


def test_unpublished_value_is_not_inferred():
    assert resolve_categorical_intent("Show hydrogen powered records", MAPPINGS) == []


def test_same_phrase_across_two_dimensions_is_ambiguous():
    mappings = [
        {"column_name": "operator", "value": "MSC"},
        {"column_name": "managing_owner", "value": "MSC"},
    ]
    assert resolve_categorical_intent("Show MSC records", mappings) == []


def test_multiword_phrase_takes_precedence_over_single_word():
    mappings = [
        {"column_name": "status", "value": "CHARTERED", "synonyms": ["chartered"]},
        {"column_name": "status", "value": "TIME", "synonyms": ["time chartered"]},
    ]
    result = resolve_categorical_intent("Show time chartered records", mappings)
    assert [x["value"] for x in result] == ["TIME"]
