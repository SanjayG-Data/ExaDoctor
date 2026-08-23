"""Selects an ExplanationProvider from environment configuration.

Only a local provider is scaffolded so far (explicit product decision:
cloud providers are deliberately deferred, not yet needed). The interface
in provider.py is provider-agnostic, so adding e.g. an Anthropic/OpenAI
provider later is additive, not a redesign.
"""

from __future__ import annotations

import os

from exadoctor.errors import ConfigurationError
from exadoctor.explain.local_llamacpp import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_FINDINGS_IN_PROMPT,
    LlamaCppProvider,
)
from exadoctor.explain.provider import ExplanationProvider

PROVIDER_VAR = "EXADOCTOR_LLM_PROVIDER"
BASE_URL_VAR = "EXADOCTOR_LLM_BASE_URL"
TIMEOUT_VAR = "EXADOCTOR_LLM_TIMEOUT_SECONDS"
MAX_TOKENS_VAR = "EXADOCTOR_LLM_MAX_TOKENS"
MAX_FINDINGS_VAR = "EXADOCTOR_LLM_MAX_FINDINGS"

_KNOWN_PROVIDERS = ("none", "local")


def get_provider(env: dict[str, str] | None = None) -> ExplanationProvider | None:
    """Returns None (no AI layer) unless EXADOCTOR_LLM_PROVIDER=local is set --
    the core tool must work identically either way. Raises ConfigurationError
    for an unrecognized provider name rather than silently returning None,
    so a typo doesn't look like "AI explanation ran and had nothing to say"."""
    env = env if env is not None else os.environ
    provider_name = env.get(PROVIDER_VAR, "none").strip().lower()

    if provider_name not in _KNOWN_PROVIDERS:
        raise ConfigurationError(
            f"Unknown {PROVIDER_VAR}={provider_name!r}. Supported values: {', '.join(_KNOWN_PROVIDERS)}."
        )

    if provider_name == "none":
        return None

    return LlamaCppProvider(
        base_url=env.get(BASE_URL_VAR, DEFAULT_BASE_URL),
        timeout=float(env.get(TIMEOUT_VAR, DEFAULT_TIMEOUT_SECONDS)),
        max_tokens=int(env.get(MAX_TOKENS_VAR, DEFAULT_MAX_TOKENS)),
        max_findings=int(env.get(MAX_FINDINGS_VAR, MAX_FINDINGS_IN_PROMPT)),
    )
