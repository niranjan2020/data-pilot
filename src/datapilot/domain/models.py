"""Core domain models for Data Pilot.

These models represent structured entities for schema discovery, SQL validation,
execution results, and provider communications without tying the domain to any
specific database engine, LLM vendor, or framework.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ColumnMetadata(BaseModel):
    """Metadata describing an individual column in a table or view."""

    name: str = Field(description="Column name")
    data_type: str = Field(description="Database data type, e.g. VARCHAR, INTEGER, TIMESTAMP")
    is_nullable: bool = Field(default=True, description="Whether the column permits NULL values")
    is_primary_key: bool = Field(default=False, description="Whether this column is part of the primary key")
    description: Optional[str] = Field(default=None, description="Human or AI-curated business description of this column")
    sample_values: List[str] = Field(default_factory=list, description="Curated sample values for disambiguation")


class ForeignKeyMetadata(BaseModel):
    """Metadata describing a relational foreign key constraint."""

    constrained_column: str = Field(description="Column name in the source table")
    referenced_table: str = Field(description="Target referenced table name")
    referenced_column: str = Field(description="Target referenced column name")


class TableMetadata(BaseModel):
    """Metadata describing a database table or view and its schema."""

    name: str = Field(description="Table name")
    schema_name: Optional[str] = Field(default=None, description="Database schema/namespace name, e.g. 'public'")
    description: Optional[str] = Field(default=None, description="Business description of what this table represents")
    columns: List[ColumnMetadata] = Field(default_factory=list, description="List of columns in this table")
    primary_keys: List[str] = Field(default_factory=list, description="Primary key column names")
    foreign_keys: List[ForeignKeyMetadata] = Field(default_factory=list, description="Foreign key relationships")

    def get_column(self, name: str) -> Optional[ColumnMetadata]:
        """Lookup a column by name (case-insensitive)."""
        lower_name = name.lower()
        for col in self.columns:
            if col.name.lower() == lower_name:
                return col
        return None


class SchemaMetadata(BaseModel):
    """Aggregated schema catalog containing tables, relationships, and engine dialect."""

    tables: List[TableMetadata] = Field(default_factory=list, description="List of tables in this schema")
    schema_name: Optional[str] = Field(default=None, description="Database schema/namespace represented by this catalog")
    dialect: str = Field(default="postgresql", description="Target SQL dialect, e.g. postgresql, mysql, snowflake")
    version: Optional[str] = Field(default=None, description="Optional schema snapshot or catalog version")

    def get_table(self, name: str) -> Optional[TableMetadata]:
        """Lookup a table by name (case-insensitive)."""
        lower_name = name.lower()
        for tbl in self.tables:
            if tbl.name.lower() == lower_name:
                return tbl
        return None


class QueryResult(BaseModel):
    """Structured execution output from a database query."""

    columns: List[str] = Field(default_factory=list, description="Column names returned in the result set")
    rows: List[List[Any]] = Field(default_factory=list, description="Row values matrix")
    row_count: int = Field(default=0, description="Total number of rows returned")
    execution_time_ms: float = Field(default=0.0, description="Execution duration in milliseconds")


class SQLValidationResult(BaseModel):
    """Structured outcome of validating an SQL statement before execution."""

    is_valid: bool = Field(description="Whether the SQL is syntactically valid and complies with safety policies")
    is_read_only: bool = Field(default=True, description="Whether the query is strictly non-mutating (SELECT only)")
    errors: List[str] = Field(default_factory=list, description="Validation or parsing errors blocking execution")
    warnings: List[str] = Field(default_factory=list, description="Advisory warnings (e.g. missing LIMIT, expensive joins)")
    sanitized_sql: Optional[str] = Field(default=None, description="Sanitized/formatted SQL if normalization occurred")
    affected_tables: List[str] = Field(default_factory=list, description="Tables identified in the query AST")


class LLMMessage(BaseModel):
    """Message payload for language model conversations."""

    role: str = Field(description="Role: 'system', 'user', or 'assistant'")
    content: str = Field(description="Textual content of the message")


class LLMResponse(BaseModel):
    """Normalized response returned by an LLM provider."""

    content: str = Field(description="Text content returned by the LLM")
    model_name: Optional[str] = Field(default=None, description="Model identifier used for generation")
    token_usage: Optional[Dict[str, int]] = Field(default=None, description="Token consumption details")
    raw_response: Optional[Dict[str, Any]] = Field(default=None, description="Optional provider-specific raw payload")
