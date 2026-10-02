"""Tests for deterministic semantic template matching."""

from datapilot.application.services.semantic_matcher import SemanticMatcher
from datapilot.domain.semantic import QueryTemplate, SemanticCatalog


def test_exact_template_synonym_match_has_high_confidence() -> None:
    catalog = SemanticCatalog(
        templates=[
            QueryTemplate(
                name="FLEET_AGE_SUMMARY",
                description="Average vessel age by operator and segment",
                synonyms=["average vessel age", "fleet age"],
                sql_template="SELECT 1",
            )
        ]
    )

    result = SemanticMatcher().match_templates(
        "show average vessel age for MSC", catalog
    )

    assert result.is_ambiguous is False
    assert result.confidence > 0
    assert result.matches[0].template.name == "FLEET_AGE_SUMMARY"


def test_close_candidates_are_marked_ambiguous() -> None:
    catalog = SemanticCatalog(
        templates=[
            QueryTemplate(
                name="FLEET_AGE_SUMMARY",
                description="Average vessel age",
                synonyms=["average vessel age"],
                sql_template="SELECT 1",
            ),
            QueryTemplate(
                name="VESSEL_AVAILABILITY",
                description="Vessel availability",
                synonyms=["vessel availability", "average vessel"],
                sql_template="SELECT 1",
            ),
        ]
    )

    result = SemanticMatcher().match_templates("average vessel", catalog)

    assert result.is_ambiguous is True
    assert len(result.matches) == 2


def test_disabled_templates_are_ignored() -> None:
    catalog = SemanticCatalog(
        templates=[
            QueryTemplate(
                name="DISABLED",
                description="Disabled template",
                synonyms=["vessel"],
                sql_template="SELECT 1",
                enabled=False,
            )
        ]
    )

    result = SemanticMatcher().match_templates("vessel", catalog)

    assert result.matches == ()
    assert result.confidence == 0.0
