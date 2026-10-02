"""SQL validator abstraction interface.

Defines the contract for analyzing, validating, and sanitizing SQL queries before
they are allowed to touch any connected database.
"""

from typing import Optional, Protocol, runtime_checkable
from datapilot.domain.models import SQLValidationResult


@runtime_checkable
class SQLValidator(Protocol):
    """Protocol for SQL safety and semantic validation.

    Ensures that generated or user-provided queries are strictly read-only,
    free of injection attacks or forbidden operations (DROP, ALTER, TRUNCATE, UPDATE, DELETE),
    and structurally sound for the target dialect.
    """

    async def validate(
        self,
        sql: str,
        dialect: Optional[str] = None,
        enforce_read_only: bool = True,
    ) -> SQLValidationResult:
        """Validate an SQL statement against syntax rules and security policies."""
        ...
