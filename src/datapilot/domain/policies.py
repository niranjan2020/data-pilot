"""Provider-independent query execution policy contracts and models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QueryExecutionPolicy(BaseModel):
    """Resource and safety limits applied before query execution."""

    timeout_seconds: float = Field(default=30.0, gt=0)
    max_result_rows: int = Field(default=1000, ge=1)
    max_query_length: int = Field(default=100_000, ge=1)
    require_limit_for_non_aggregate: bool = True
    default_limit: int = Field(default=1000, ge=1)
    max_limit: int = Field(default=1000, ge=1)


class QueryPolicyResult(BaseModel):
    """Result of applying an execution policy to one SQL statement."""

    is_allowed: bool
    sql: str
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
