"""Domain-independent, approved ranking policy contract.

A ranking policy selects *which entities* enter a Top-N cohort. It is not
itself a metric and must not be inferred from a display label.
"""
from dataclasses import dataclass
from enum import Enum


class RankingScope(str, Enum):
    GLOBAL = "global"
    PER_GROUP = "per_group"


class RankingDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class RankingTiePolicy(str, Enum):
    EXACT_N = "exact_n"
    INCLUDE_TIES = "include_ties"


@dataclass(frozen=True)
class RankingPolicy:
    """A reviewed ranking definition, independent of SQL dialect or domain."""

    name: str
    entity: str
    dimension: str
    metric: str
    direction: RankingDirection = RankingDirection.DESC
    scope: RankingScope = RankingScope.GLOBAL
    default_n: int = 10
    maximum_n: int = 100
    tie_policy: RankingTiePolicy = RankingTiePolicy.EXACT_N
    published: bool = False

    def __post_init__(self) -> None:
        for field in ("name", "entity", "dimension", "metric"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ValueError(f"Ranking policy requires {field}")
        if not isinstance(self.default_n, int) or isinstance(self.default_n, bool):
            raise ValueError("default_n must be an integer")
        if not isinstance(self.maximum_n, int) or isinstance(self.maximum_n, bool):
            raise ValueError("maximum_n must be an integer")
        if self.default_n < 1 or self.maximum_n < self.default_n:
            raise ValueError("Ranking policy requires 1 <= default_n <= maximum_n")
        if not isinstance(self.direction, RankingDirection):
            raise ValueError("Invalid ranking direction")
        if not isinstance(self.scope, RankingScope):
            raise ValueError("Invalid ranking scope")
        if not isinstance(self.tie_policy, RankingTiePolicy):
            raise ValueError("Invalid ranking tie policy")

    def resolve_n(self, requested_n: int | None = None) -> int:
        """Resolve user N against the approved policy ceiling."""
        if not self.published:
            raise ValueError("Unpublished ranking policy cannot be executed")
        n = self.default_n if requested_n is None else requested_n
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= self.maximum_n:
            raise ValueError("Requested ranking N exceeds the approved bounds")
        return n


@dataclass(frozen=True)
class RankingPlan:
    """Resolved cohort selection, separate from the final output aggregation.

    The ranking metric chooses members of the cohort. The output metric may
    differ (e.g. rank by capacity, report vessel counts).
    """

    policy: RankingPolicy
    n: int
    output_metric: str
    partition_dimension: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output_metric, str) or not self.output_metric.strip():
            raise ValueError("Ranking output metric must be explicit")
        if self.policy.scope == RankingScope.PER_GROUP:
            if not isinstance(self.partition_dimension, str) or not self.partition_dimension.strip():
                raise ValueError("Per-group ranking requires a partition dimension")
        elif self.partition_dimension is not None:
            raise ValueError("Global ranking must not define a ranking partition")


def resolve_ranking_plan(
    policy: RankingPolicy,
    *,
    output_metric: str,
    requested_n: int | None = None,
    partition_dimension: str | None = None,
) -> RankingPlan:
    """Resolve an approved cohort plan without generating SQL or guessing scope."""
    return RankingPlan(
        policy=policy,
        n=policy.resolve_n(requested_n),
        output_metric=output_metric,
        partition_dimension=partition_dimension,
    )
