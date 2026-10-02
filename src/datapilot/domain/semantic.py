"""Semantic-layer domain models for Data Pilot.

These models capture business meaning independently of any LLM vendor or
database engine. They are the foundation for entity/value resolution, metric definitions,
business rules, and ambiguity handling.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class SemanticConcept(BaseModel):
    """A business concept mapped to one or more database objects."""

    name: str = Field(description="Stable business concept name")
    description: str = Field(description="Human-readable business definition")
    synonyms: List[str] = Field(default_factory=list, description="Alternative user terms")
    table_names: List[str] = Field(default_factory=list, description="Relevant catalog tables")
    column_names: List[str] = Field(default_factory=list, description="Relevant catalog columns")


class EntityAttributeDefinition(BaseModel):
    """A semantic attribute that can be used to filter or resolve an entity."""

    name: str = Field(description="Stable semantic attribute name")
    description: Optional[str] = Field(default=None, description="Attribute meaning")
    synonyms: List[str] = Field(default_factory=list)
    column_name: str = Field(description="Canonical database column")
    operators: List[str] = Field(
        default_factory=lambda: ["="],
        description="Allowed semantic operators for this attribute",
    )


class EntityDefinition(BaseModel):
    """Business entity and its canonical database representation."""

    name: str = Field(description="Stable entity name")
    description: Optional[str] = Field(default=None, description="Entity meaning")
    synonyms: List[str] = Field(default_factory=list)
    table_name: str = Field(description="Canonical table containing the entity")
    key_column: str = Field(description="Canonical identifier column")
    display_column: Optional[str] = Field(default=None, description="Human-readable display column")
    attributes: List[EntityAttributeDefinition] = Field(
        default_factory=list,
        description="Semantic attributes available for entity resolution and filtering",
    )


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



class ResolvedEntity(BaseModel):
    """Entity selected from the semantic catalog for a user question."""

    name: str
    table_name: str
    key_column: str
    display_column: Optional[str] = None
    confidence: float = 0.0
    matched_terms: List[str] = Field(default_factory=list)


class ResolvedFilter(BaseModel):
    """A semantic filter resolved to a canonical database column and value."""

    attribute: str
    column_name: str
    operator: str = "="
    value: str
    confidence: float = 0.0
    source_text: Optional[str] = None


class QueryIntent(BaseModel):
    """Provider-independent semantic interpretation of a natural-language question."""

    entity: Optional[ResolvedEntity] = None
    filters: List[ResolvedFilter] = Field(default_factory=list)
    confidence: float = 0.0
    ambiguities: List[str] = Field(default_factory=list)


class SemanticCatalog(BaseModel):
    """Complete semantic context available to the NL-to-SQL orchestrator."""

    concepts: List[SemanticConcept] = Field(default_factory=list)
    entities: List[EntityDefinition] = Field(default_factory=list)
    metrics: List[MetricDefinition] = Field(default_factory=list)
    business_rules: List[BusinessRule] = Field(default_factory=list)
