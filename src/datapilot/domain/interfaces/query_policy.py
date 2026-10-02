"""Contract for query resource-policy enforcement."""

from typing import Optional, Protocol, runtime_checkable

from datapilot.domain.policies import QueryExecutionPolicy, QueryPolicyResult


@runtime_checkable
class QueryPolicyEnforcer(Protocol):
    """Apply resource limits without depending on a database provider."""

    def enforce(
        self,
        sql: str,
        dialect: Optional[str],
        policy: QueryExecutionPolicy,
    ) -> QueryPolicyResult:
        ...
