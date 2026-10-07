from pydantic import ValidationError
import pytest

from datapilot.domain.interfaces.ai_configuration import (
    AIProviderConfiguration,
    AIProviderKind,
    AIProviderSecretInput,
)


def test_provider_configuration_is_provider_independent_and_secret_free():
    configuration = AIProviderConfiguration(
        provider=AIProviderKind.OPENAI,
        model="provider-model",
        endpoint="https://example.invalid",
        configured=True,
        credential_configured=True,
    )
    payload = configuration.model_dump(mode="json")
    assert payload["provider"] == "openai"
    assert "api_key" not in payload
    assert "secret" not in payload
    assert "password" not in payload


@pytest.mark.parametrize("provider", list(AIProviderKind))
def test_supported_provider_kinds_have_one_stable_contract(provider):
    configuration = AIProviderConfiguration(provider=provider, model="model")
    assert configuration.provider == provider


def test_secret_input_requires_non_empty_credential():
    with pytest.raises(ValidationError):
        AIProviderSecretInput(api_key="")
