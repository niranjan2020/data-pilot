"""Domain contracts for the natural-language query workflow."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from datapilot.domain.semantic import QueryIntent


class QueryRequest(BaseModel):
    """A user question plus optional explicit parameters."""

    question: str = Field(min_length=1)
    parameters: Dict[str, Any] = Field(default_factory=dict)


class SQLGeneration(BaseModel):
    """Structured SQL proposal produced by an SQL generation adapter."""

    sql: str = Field(min_length=1)
    explanation: Optional[str] = None


class AmbiguityCandidate(BaseModel):
    """A semantic template candidate presented to the caller."""

    name: str
    description: str
    score: float
    matched_terms: List[str] = Field(default_factory=list)


class QueryResponse(BaseModel):
    """End-to-end result of the Data Pilot query orchestration workflow."""

    question: str
    status: Literal["completed", "ambiguous", "rejected"]
    source: Optional[Literal["template", "generator"]] = None
    sql: Optional[str] = None
    result: Optional[Any] = None
    confidence: float = 0.0
    matched_template: Optional[str] = None
    ambiguity_candidates: List[AmbiguityCandidate] = Field(default_factory=list)
    semantic_ambiguities: List[str] = Field(default_factory=list)
    resolved_intent: Optional[QueryIntent] = None
    validation_warnings: List[str] = Field(default_factory=list)
    message: Optional[str] = None
