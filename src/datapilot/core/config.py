"""Configuration management for Data Pilot using Pydantic Settings."""

from functools import lru_cache
from typing import List, Optional
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env files."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # General Application
    app_name: str = Field(default="Data Pilot", description="Display name of the application")
    app_version: str = Field(default="0.1.0", description="Semantic version of the application")
    environment: str = Field(default="development", description="Environment: development, staging, production, test")
    debug: bool = Field(default=False, description="Enable debug mode and reload")

    # Server Bindings
    host: str = Field(default="0.0.0.0", description="Server host interface")
    port: int = Field(default=8000, description="Server port")

    # Logging
    log_level: str = Field(default="INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    log_format: str = Field(default="console", description="Logging format: console or json")

    # Database Configuration (Pluggable)
    default_database_url: Optional[str] = Field(
        default=None,
        description="Default connection string for the primary analytical/transactional database (e.g. postgresql://...)",
    )
    database_pool_size: int = Field(default=5, description="Connection pool size for database connections")
    database_query_timeout_seconds: float = Field(default=30.0, description="Default timeout for query execution")
    metadata_database_url: Optional[str] = Field(
        default=None,
        description="Optional PostgreSQL URL for the Data Pilot metadata catalog; defaults to the primary database when omitted",
    )
    metadata_database_pool_size: int = Field(default=3, description="Metadata catalog connection pool size")

    # LLM Provider Configuration (Pluggable)
    default_llm_provider: str = Field(
        default="gemini",
        description="Default LLM provider: gemini, openai, anthropic, or local",
    )
    gemini_api_key: Optional[SecretStr] = Field(default=None, description="Google Gemini API key")
    openai_api_key: Optional[SecretStr] = Field(default=None, description="OpenAI API key")
    anthropic_api_key: Optional[SecretStr] = Field(default=None, description="Anthropic API key")

    # Security & CORS (Local development defaults; credentials disabled by default)
    cors_origins: List[str] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8000",
        ],
        description="Allowed CORS origins for the HTTP API",
    )
    cors_allow_credentials: bool = Field(
        default=False,
        description="Enable CORS credentials (disabled by default for security)",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton instance of the application settings."""
    return Settings()
