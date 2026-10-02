"""Semantic-layer domain models for Data Pilot.

These models capture business meaning independently of any LLM vendor or
database engine. They are the foundation for deterministic template matching,
entity resolution, metric definitions, and ambiguity handling.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class SemanticConcept(BaseModel):
    """A business concept mapped to one or more database objects."""

    name: str = Field(description="Stable business concept name")
    description: str = Field(description="Human-readable business definition")
    synonyms: List[str] = Field(default_factory=list, description="Alternative user terms")
    table_names: List[str] = Field(default_factory=list, description="Relevant catalog tables")
    column_names: List[str] = Field(default_factory=list, description="Relevant catalog columns")


class EntityDefinition(BaseModel):
    """Business entity and its canonical database representation."""

    name: str = Field(description="Stable entity name")
    description: Optional[str] = Field(default=None, description="Entity meaning")
    synonyms: List[str] = Field(default_factory=list)
    table_name: str = Field(description="Canonical table containing the entity")
    key_column: str = Field(description="Canonical identifier column")
    display_column: Optional[str] = Field(default=None, description="Human-readable display column")


class MetricDefinition(BaseModel):
    """Reusable metric definition with an explicit SQL expression."""

    name: str = Field(description="Stable metric name")
    description: str = Field(description="Business definition of the metric")
    synonyms: List[str] = Field(default_factory=list)
    expression: str = Field(description="Read-only SQL expression evaluated in query context")
    default_table: Optional[str] = Field(default=None)
    dimensions: List[str] = Field(default_factory=list, description="Allowed grouping dimensions")


class BusinessRule(BaseModel):
    """Deterministic business rule that must be respected by query generation."""

    name: str = Field(description="Stable rule name")
    description: str = Field(description="Human-readable rule")
    condition: str = Field(description="Machine-readable condition or SQL predicate")
    priority: int = Field(default=100, ge=0, description="Lower values run first")


class QueryTemplate(BaseModel):
    """Reusable parameterized query intent.

    Templates are preferred over free-form generation when confidence is high.
    """

    name: str = Field(description="Stable template identifier")
    description: str = Field(description="Intent represented by the template")
    synonyms: List[str] = Field(default_factory=list)
    sql_template: str = Field(description="Parameterized read-only SQL template")
    required_parameters: List[str] = Field(default_factory=list)
    optional_parameters: List[str] = Field(default_factory=list)
    priority: int = Field(default=100, ge=0)
    enabled: bool = True


class SemanticCatalog(BaseModel):
    """Complete semantic context available to the NL-to-SQL orchestrator."""

    concepts: List[SemanticConcept] = Field(default_factory=list)
    entities: List[EntityDefinition] = Field(default_factory=list)
    metrics: List[MetricDefinition] = Field(default_factory=list)
    business_rules: List[BusinessRule] = Field(default_factory=list)
    templates: List[QueryTemplate] = Field(default_factory=list)
