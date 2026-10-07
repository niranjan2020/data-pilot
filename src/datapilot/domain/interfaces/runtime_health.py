"""Provider-independent runtime health contracts."""

from __future__ import annotations
from typing import Protocol
from pydantic import BaseModel


class RuntimeComponentHealth(BaseModel):
    status: str
    details: dict[str, object] | None = None


class RuntimeHealthChecker(Protocol):
    async def check(self) -> dict[str, RuntimeComponentHealth]:
        """Return safe runtime component health without exposing credentials."""
        ...
