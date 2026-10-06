"""Unit tests verifying domain models and runtime-checkable protocol contracts."""

from typing import Any, Dict, List, Optional, Type, TypeVar
import pytest
from pydantic import BaseModel
from datapilot.domain.interfaces.database import DatabaseProvider
from datapilot.domain.interfaces.llm import LLMProvider
from datapilot.domain.interfaces.metadata import MetadataProvider
from datapilot.domain.interfaces.sql_generator import SQLGenerator
from datapilot.domain.interfaces.sql_binder import SQLIdentifierBinder
from datapilot.domain.interfaces.sql_validator import SQLValidator
from datapilot.domain.execution_recovery import ExecutionRecoveryEvidence
from datapilot.domain.models import (
    ColumnMetadata,
    LLMMessage,
    LLMResponse,
    QueryResult,
    SQLValidationResult,
    SchemaMetadata,
    TableMetadata,
)

T = TypeVar("T", bound=BaseModel)


class DummyDatabaseProvider:
    """Mock implementation satisfying DatabaseProvider protocol for verification."""

    @property
    def dialect(self) -> str:
        return "postgresql"

    def classify_execution_error(self, details=None) -> ExecutionRecoveryEvidence:
        return ExecutionRecoveryEvidence(
            recoverable=False,
            category="unknown",
            reason="dummy provider classification",
            provider=self.dialect,
        )

    async def ping(self) -> bool:
        return True

    async def introspect_schema(self, schema_name: Optional[str] = None) -> SchemaMetadata:
        return SchemaMetadata(tables=[], dialect="postgresql")

    async def execute_query(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> QueryResult:
        return QueryResult(columns=["id"], rows=[[1]], row_count=1)

    async def close(self) -> None:
        pass


class DummyLLMProvider:
    """Mock implementation satisfying LLMProvider protocol for verification."""

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        stop_sequences: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return LLMResponse(content="SELECT 1;")

    async def generate_structured(
        self,
        messages: List[LLMMessage],
        response_schema: Type[T],
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> T:
        return response_schema.model_validate({})


class DummyMetadataProvider:
    """Mock implementation satisfying MetadataProvider protocol for verification."""

    async def get_schema(self, schema_name: Optional[str] = None) -> Optional[SchemaMetadata]:
        return SchemaMetadata(tables=[], dialect="postgresql")

    async def save_schema(self, schema: SchemaMetadata) -> None:
        pass

    async def get_table(self, table_name: str, schema_name: Optional[str] = None) -> Optional[TableMetadata]:
        return None

    async def list_tables(self, schema_name: Optional[str] = None) -> List[str]:
        return []


class DummySQLGenerator:
    """Mock implementation satisfying SQLGenerator protocol for verification."""

    async def generate(
        self,
        question: str,
        schema: SchemaMetadata,
        context: Optional[Dict[str, Any]] = None,
        dialect: Optional[str] = None,
    ) -> str:
        return "SELECT count(*) FROM vessels WHERE status = 'on-order';"


class DummySQLIdentifierBinder:
    """Mock implementation satisfying SQLIdentifierBinder protocol."""

    def bind(self, sql: str, schema: SchemaMetadata, dialect: str) -> str:
        return sql


class DummySQLValidator:
    """Mock implementation satisfying SQLValidator protocol for verification."""

    async def validate(
        self,
        sql: str,
        dialect: Optional[str] = None,
        enforce_read_only: bool = True,
    ) -> SQLValidationResult:
        return SQLValidationResult(is_valid=True, is_read_only=True)


def test_database_provider_protocol_conformance():
    """Verify that a compliant class satisfies DatabaseProvider protocol."""
    provider = DummyDatabaseProvider()
    assert isinstance(provider, DatabaseProvider)
    assert provider.dialect == "postgresql"


def test_llm_provider_protocol_conformance():
    """Verify that a compliant class satisfies LLMProvider protocol."""
    provider = DummyLLMProvider()
    assert isinstance(provider, LLMProvider)
    assert provider.provider_name == "gemini"


def test_metadata_provider_protocol_conformance():
    """Verify that a compliant class satisfies MetadataProvider protocol."""
    provider = DummyMetadataProvider()
    assert isinstance(provider, MetadataProvider)


def test_sql_generator_protocol_conformance():
    """Verify that a compliant class satisfies SQLGenerator protocol."""
    generator = DummySQLGenerator()
    assert isinstance(generator, SQLGenerator)


def test_sql_identifier_binder_protocol_conformance():
    binder = DummySQLIdentifierBinder()
    assert isinstance(binder, SQLIdentifierBinder)


def test_sql_validator_protocol_conformance():
    """Verify that a compliant class satisfies SQLValidator protocol."""
    validator = DummySQLValidator()
    assert isinstance(validator, SQLValidator)


def test_schema_metadata_lookup():
    """Verify case-insensitive table and column lookup in SchemaMetadata."""
    col = ColumnMetadata(name="vessel_id", data_type="INTEGER", is_primary_key=True)
    table = TableMetadata(name="Vessels", columns=[col], primary_keys=["vessel_id"])
    schema = SchemaMetadata(tables=[table], dialect="postgresql")

    found_table = schema.get_table("vessels")
    assert found_table is not None
    assert found_table.name == "Vessels"

    found_col = found_table.get_column("VESSEL_ID")
    assert found_col is not None
    assert found_col.is_primary_key is True
