"""Domain contracts for the natural-language query workflow."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from datapilot.domain.semantic import QueryIntent


class QueryRequest(BaseModel):
    """A user question plus optional explicit parameters."""

    question: str = Field(min_length=1)
    source_name: Optional[str] = Field(default=None, description="Configured data-source name used for semantic retrieval")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = Field(
        default=False,
        description="Build and validate the query plan without executing SQL against the source database",
    )
    clarification_selections: Dict[str, str] = Field(
        default_factory=dict,
        description="Explicit user selections used to resume a previously ambiguous query",
    )
    follow_up_to_history_id: Optional[int] = Field(
        default=None,
        ge=1,
        description="Explicit prior query-history item whose analytical context should be carried into this follow-up",
    )


class SQLGeneration(BaseModel):
    """Structured SQL proposal produced by an SQL generation adapter."""

    sql: str = Field(min_length=1)
    explanation: Optional[str] = None


class QueryTrace(BaseModel):
    """Structured diagnostic trace of semantic retrieval and query planning."""

    retrieval_stage: str = "hierarchical_seeds"
    retrieved_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    llm_messages: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Exact system/user messages supplied to the SQL-generation LLM, for admin diagnostics",
    )
    governed_datasets: List[str] = Field(default_factory=list)
    governed_entities: List[str] = Field(default_factory=list)
    governed_relationships: List[str] = Field(default_factory=list)
    governed_metrics: List[str] = Field(default_factory=list)
    governed_business_rules: List[str] = Field(default_factory=list)
    governed_time_dimensions: List[str] = Field(default_factory=list)
    time_interpretation: Dict[str, Any] = Field(default_factory=dict)
    physical_tables: List[str] = Field(default_factory=list)
    physical_columns: Dict[str, List[str]] = Field(default_factory=dict)
    context_budget: Dict[str, Any] = Field(default_factory=dict)
    resolved_parameters: Dict[str, Any] = Field(default_factory=dict)
    generated_sql: Optional[str] = None
    bound_sql: Optional[str] = None
    validated_sql: Optional[str] = None
    validation_affected_tables: List[str] = Field(default_factory=list)
    validation_warnings: List[str] = Field(default_factory=list)
    correctness_checks: List[Dict[str, Any]] = Field(default_factory=list, description="Deterministic semantic/physical alignment checks performed before execution")
    policy_sql: Optional[str] = None
    policy_warnings: List[str] = Field(default_factory=list)
    execution: Dict[str, Any] = Field(default_factory=dict)
    clarification_selections: Dict[str, str] = Field(
        default_factory=dict,
        description="Effective governed clarification choices, including inherited follow-up selections",
    )
    conversation_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Explicit carried-forward context for a follow-up query; prior SQL is never reused",
    )


class ClarificationOption(BaseModel):
    """One explicit governed interpretation the user can choose."""

    value: str
    label: str
    description: Optional[str] = None


class ClarificationRequest(BaseModel):
    """Structured ambiguity returned before SQL generation."""

    kind: Literal["entity", "time_dimension", "metric", "attribute"]
    key: str
    question: str
    options: List[ClarificationOption] = Field(default_factory=list)


class QueryResponse(BaseModel):
    """End-to-end result of the Data Pilot query orchestration workflow."""

    question: str
    status: Literal["completed", "dry_run", "ambiguous", "rejected"]
    source: Optional[Literal["generator"]] = None
    sql: Optional[str] = None
    result: Optional[Any] = None
    confidence: float = 0.0
    semantic_ambiguities: List[str] = Field(default_factory=list)
    clarification: Optional[ClarificationRequest] = None
    resolved_intent: Optional[QueryIntent] = None
    retrieved_context: List[Dict[str, Any]] = Field(default_factory=list)
    validation_warnings: List[str] = Field(default_factory=list)
    trace: Optional[QueryTrace] = None
    presentation: Optional[Dict[str, Any]] = Field(default=None, description="Deterministic result-presentation plan derived from result shape and query semantics")
    result_summary: Optional[Dict[str, Any]] = Field(default=None, description="Grounded natural-language answer derived only from executed result rows")
    message: Optional[str] = None
    history_id: Optional[int] = Field(
        default=None,
        description="Persisted query-history id when the response is returned through the HTTP API",
    )
