from datapilot.application.services.semantic_context import resolve_published_dimension_owners


def test_resolves_approved_dimension():
    assert resolve_published_dimension_owners("count by region", [{"entity_id": 2, "name": "Region"}]) == {2}


def test_does_not_match_unpublished_near_name():
    assert resolve_published_dimension_owners("count by region_next", [{"entity_id": 2, "name": "Region"}]) == set()


def test_ambiguous_owners_are_not_selected():
    grants = [{"entity_id": 1, "name": "Region"}, {"entity_id": 2, "name": "Region"}]
    assert resolve_published_dimension_owners("count by region", grants) == set()


def test_specific_phrase_wins():
    grants = [{"entity_id": 1, "name": "Owner"}, {"entity_id": 2, "name": "Current Owner"}]
    assert resolve_published_dimension_owners("count by current owner", grants) == {2}
