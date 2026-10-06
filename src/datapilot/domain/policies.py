"""Provider-independent query execution policy contracts and models."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class QueryExecutionPolicy(BaseModel):
    """Resource and safety limits applied before query execution."""

    timeout_seconds: float = Field(default=30.0, gt=0)
    max_result_rows: int = Field(default=1000, ge=1)
    max_query_length: int = Field(default=100_000, ge=1)
    require_limit_for_non_aggregate: bool = True
    default_limit: int = Field(default=1000, ge=1)
    max_limit: int = Field(default=1000, ge=1)

    @model_validator(mode="after")
    def validate_resource_budget(self) -> "QueryExecutionPolicy":
        if self.default_limit > self.max_limit:
            raise ValueError("default_limit must be less than or equal to max_limit")
        if self.max_limit > self.max_result_rows:
            raise ValueError("max_limit must be less than or equal to max_result_rows")
        return self

    def resource_budget(self) -> dict[str, float | int | bool]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_result_rows": self.max_result_rows,
            "max_query_length": self.max_query_length,
            "require_limit_for_non_aggregate": self.require_limit_for_non_aggregate,
            "default_limit": self.default_limit,
            "max_limit": self.max_limit,
        }


class QueryPolicyResult(BaseModel):
    """Result of applying an execution policy to one SQL statement."""

    is_allowed: bool
    sql: str
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
