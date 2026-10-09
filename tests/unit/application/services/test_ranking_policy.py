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


from datapilot.application.services.ranking_policy import resolve_ranking_plan


def test_ranking_cohort_metric_is_distinct_from_output_metric():
    policy = RankingPolicy(
        name="Capacity cohort", entity="Vessel", dimension="operator",
        metric="Approved Capacity", published=True,
    )
    plan = resolve_ranking_plan(
        policy, output_metric="On Order Vessel Count", requested_n=5,
    )
    assert plan.policy.metric == "Approved Capacity"
    assert plan.output_metric == "On Order Vessel Count"
    assert plan.n == 5
    assert plan.partition_dimension is None


def test_per_group_ranking_requires_explicit_partition_dimension():
    policy = RankingPolicy(
        name="Revenue cohort", entity="Customer", dimension="customer",
        metric="Revenue", scope=RankingScope.PER_GROUP, published=True,
    )
    with pytest.raises(ValueError, match="partition dimension"):
        resolve_ranking_plan(policy, output_metric="Order Count")
    plan = resolve_ranking_plan(
        policy, output_metric="Order Count", partition_dimension="region",
    )
    assert plan.partition_dimension == "region"


def test_global_ranking_cannot_silently_become_per_group():
    policy = RankingPolicy(
        name="Units cohort", entity="Product", dimension="product",
        metric="Units Sold", published=True,
    )
    with pytest.raises(ValueError, match="Global ranking"):
        resolve_ranking_plan(
            policy, output_metric="Revenue", partition_dimension="category",
        )


def test_ranking_plan_rejects_unpublished_policy_and_missing_output_metric():
    unpublished = RankingPolicy(
        name="Draft", entity="Product", dimension="product", metric="Revenue",
    )
    with pytest.raises(ValueError, match="Unpublished"):
        resolve_ranking_plan(unpublished, output_metric="Units")
    published = RankingPolicy(
        name="Published", entity="Product", dimension="product",
        metric="Revenue", published=True,
    )
    with pytest.raises(ValueError, match="output metric"):
        resolve_ranking_plan(published, output_metric="")
