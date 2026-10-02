"""Unit tests verifying configuration loading and validation."""

import pytest
from datapilot.core.config import Settings, get_settings


def test_default_settings():
    """Verify default configuration values."""
    settings = Settings()
    assert settings.app_name == "Data Pilot"
    assert settings.app_version == "0.1.0"
    assert settings.environment == "development"
    assert settings.debug is False
    assert settings.host == "0.0.0.0"
    assert isinstance(settings.port, int)
    assert settings.default_llm_provider == "gemini"


def test_custom_settings_override():
    """Verify settings can be initialized with custom overrides."""
    custom = Settings(
        app_name="Custom Pilot",
        environment="staging",
        debug=True,
        port=9000,
        default_llm_provider="openai",
        gemini_api_key="super-secret-key",
    )
    assert custom.app_name == "Custom Pilot"
    assert custom.environment == "staging"
    assert custom.debug is True
    assert custom.port == 9000
    assert custom.default_llm_provider == "openai"
    # Ensure SecretStr masks value on repr/str
    assert "super-secret-key" not in str(custom.gemini_api_key)
    assert custom.gemini_api_key.get_secret_value() == "super-secret-key"


def test_cors_defaults_secure():
    """Verify default CORS configuration does not enable open credentials."""
    settings = Settings()
    assert settings.cors_allow_credentials is False
    assert any("localhost" in origin for origin in settings.cors_origins)


def test_get_settings_cached():
    """Verify get_settings returns a cached instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
