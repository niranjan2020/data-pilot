"""Exception hierarchy for the Data Pilot platform."""

from typing import Any, Dict, Optional


class DataPilotError(Exception):
    """Base exception for all Data Pilot errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


class ConfigurationError(DataPilotError):
    """Raised when there is an issue with application or provider configuration."""
    pass


class ProviderError(DataPilotError):
    """Raised when an external provider (database, LLM, catalog) encounters an error."""
    pass


class DatabaseError(ProviderError):
    """Base error for database provider operations."""
    pass


class DatabaseConnectionError(DatabaseError):
    """Raised when unable to establish or maintain connection to the database."""
    pass


class DatabaseExecutionError(DatabaseError):
    """Raised when query execution against the database fails."""
    pass


class LLMError(ProviderError):
    """Base error for LLM provider operations."""
    pass


class MetadataError(DataPilotError):
    """Raised when reading, caching, or writing schema catalog metadata fails."""
    pass


class SQLGenerationError(DataPilotError):
    """Raised when SQL synthesis or translation fails."""
    pass


class SQLValidationError(DataPilotError):
    """Raised when generated SQL violates safety constraints or validation rules."""
    pass
