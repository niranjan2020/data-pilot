import pytest

from datapilot.application.services.ranking_policy import (
    RankingDirection,
    RankingPolicy,
    RankingScope,
    RankingTiePolicy,
)


def test_published_ranking_policy_resolves_default_and_requested_n():
    policy = RankingPolicy(
        name="Approved operator ranking",
        entity="Vessel",
        dimension="operator",
        metric="Total Capacity",
        direction=RankingDirection.DESC,
        scope=RankingScope.GLOBAL,
        default_n=10,
        maximum_n=50,
        published=True,
    )
    assert policy.resolve_n() == 10
    assert policy.resolve_n(20) == 20


def test_unpublished_policy_cannot_be_executed():
    policy = RankingPolicy(
        name="Revenue ranking", entity="Customer",
        dimension="customer_id", metric="Revenue",
    )
    with pytest.raises(ValueError, match="Unpublished"):
        policy.resolve_n()


@pytest.mark.parametrize("requested", [0, -1, 101, True, 1.5])
def test_ranking_rejects_invalid_or_excessive_n(requested):
    policy = RankingPolicy(
        name="Units ranking", entity="Product", dimension="product_id",
        metric="Units Sold", maximum_n=100, published=True,
    )
    with pytest.raises(ValueError):
        policy.resolve_n(requested)


def test_policy_supports_per_group_and_tie_semantics():
    policy = RankingPolicy(
        name="Segment ranking", entity="Vessel", dimension="operator",
        metric="Total Capacity", scope=RankingScope.PER_GROUP,
        tie_policy=RankingTiePolicy.INCLUDE_TIES, published=True,
    )
    assert policy.scope == RankingScope.PER_GROUP
    assert policy.tie_policy == RankingTiePolicy.INCLUDE_TIES


@pytest.mark.parametrize("kwargs", [
    {"name": ""},
    {"metric": ""},
    {"default_n": 0},
    {"default_n": 11, "maximum_n": 10},
    {"maximum_n": True},
    {"direction": "down"},
])
def test_policy_rejects_invalid_definition(kwargs):
    params = dict(name="Ranking", entity="Asset", dimension="category", metric="Value")
    params.update(kwargs)
    with pytest.raises(ValueError):
        RankingPolicy(**params)
