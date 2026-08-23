import pytest

from exadoctor.errors import ConfigurationError
from exadoctor.explain.factory import get_provider
from exadoctor.explain.local_llamacpp import LlamaCppProvider


def test_get_provider_defaults_to_none() -> None:
    assert get_provider({}) is None


def test_get_provider_explicit_none() -> None:
    assert get_provider({"EXADOCTOR_LLM_PROVIDER": "none"}) is None


def test_get_provider_local_returns_llamacpp_provider() -> None:
    provider = get_provider(
        {
            "EXADOCTOR_LLM_PROVIDER": "local",
            "EXADOCTOR_LLM_BASE_URL": "http://example.internal:9000",
            "EXADOCTOR_LLM_TIMEOUT_SECONDS": "12",
            "EXADOCTOR_LLM_MAX_TOKENS": "77",
        }
    )
    assert isinstance(provider, LlamaCppProvider)
    assert provider._base_url == "http://example.internal:9000"
    assert provider._timeout == 12.0
    assert provider._max_tokens == 77


def test_get_provider_local_uses_defaults_when_unset() -> None:
    provider = get_provider({"EXADOCTOR_LLM_PROVIDER": "local"})
    assert isinstance(provider, LlamaCppProvider)


def test_get_provider_rejects_unknown_provider_name() -> None:
    with pytest.raises(ConfigurationError, match="Unknown"):
        get_provider({"EXADOCTOR_LLM_PROVIDER": "lcoal"})
