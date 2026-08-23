"""Integration layer: real HTTP call to the local llama.cpp server.

Skipped unless EXADOCTOR_LLM_PROVIDER=local is set -- this suite hits a
real, possibly slow (CPU inference, ~1 token/sec observed) local model, so
it's opt-in like the DB integration tests, not run by default.
"""

from __future__ import annotations

import os

import pytest

from exadoctor.explain.local_llamacpp import LlamaCppProvider
from exadoctor.models.finding import Finding, FindingStatus

pytestmark = pytest.mark.skipif(
    os.environ.get("EXADOCTOR_LLM_PROVIDER") != "local",
    reason="Set EXADOCTOR_LLM_PROVIDER=local to run against a real local LLM server.",
)


def test_explain_against_real_local_server() -> None:
    finding = Finding(
        id="SYS-SWAP-001",
        title="Swap activity detected",
        category="system",
        status=FindingStatus.WARNING,
        summary="Swap activity observed in 2 of 1123 monitoring samples; peak 0.4 MiB/s.",
    )
    # Small max_tokens to keep this fast against a ~1 token/sec CPU model.
    provider = LlamaCppProvider(max_tokens=20)
    result = provider.explain([finding])

    assert isinstance(result, str)
    assert len(result) > 0
