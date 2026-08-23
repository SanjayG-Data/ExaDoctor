"""Local LLM explanation provider via a self-hosted llama.cpp server.

Calls the server's OpenAI-compatible `/v1/chat/completions` endpoint over
plain HTTP -- this is NOT a database operation and does not go through
ReadOnlyGateway at all (verified live: the running server at
http://localhost:8080, serving Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf,
responds correctly to this exact request shape). Uses only the stdlib
(urllib) rather than adding an HTTP client dependency for one POST call.

Observed live against that server: BOTH prompt processing and generation
are slow (CPU inference, no GPU) -- roughly 170ms/token for prompt
processing and roughly 1000ms/token for generation. A naive prompt sending
every finding's full JSON (evidence, limitations, documentation) for a
scan with ~18 findings would put prompt processing alone in the 5-10
minute range -- unacceptable for something the user explicitly opts into
per-command. Two mitigations, both load-bearing, not cosmetic:
  1. Only a compact per-finding summary (id/status/title/summary/
     recommendation) is sent, not the full Finding.to_dict().
  2. The number of findings included is capped (MAX_FINDINGS_IN_PROMPT);
     anything beyond that is noted as omitted, not silently dropped.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from exadoctor.errors import ExplanationProviderError
from exadoctor.models.finding import Finding

DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_MAX_TOKENS = 220
MAX_FINDINGS_IN_PROMPT = 15

_SYSTEM_PROMPT = (
    "You are explaining diagnostic findings from ExaDoctor, a deterministic "
    "Exasol database diagnostic tool. You did not produce these findings and "
    "have no database access of your own. Your job is strictly limited to:\n"
    "- Summarizing and prioritizing the findings for a human reader.\n"
    "- Explaining Exasol terminology in plain language.\n"
    "- Proposing investigation questions, explicitly marked as suggestions.\n"
    "You must NEVER:\n"
    "- Change, upgrade, or downgrade any finding's severity or status.\n"
    "- Invent evidence, metrics, or facts not present in the findings given.\n"
    "- Suggest or describe executing any SQL or administrative action.\n"
    "- Present generic database advice as official Exasol guidance.\n"
    "Be concise: a short prioritized summary, not an essay. If a finding "
    "lacks enough detail to explain confidently, say so rather than guessing."
)


def _compact_finding(finding: Finding) -> dict[str, str]:
    """Deliberately narrow: id/status/title/summary/recommendation only.
    Evidence/limitations/documentation are dropped from the prompt -- they
    matter for a human reading the deterministic report, but bloat the
    prompt for comparatively little summarization value, and this model is
    slow enough that prompt size directly controls wall-clock time."""
    return {
        "id": finding.id,
        "status": finding.status.value,
        "title": finding.title,
        "summary": finding.summary,
        "recommendation": finding.recommendation or "",
    }


def _build_user_message(findings: list[Finding], max_findings: int = MAX_FINDINGS_IN_PROMPT) -> str:
    truncated = findings[:max_findings]
    omitted = len(findings) - len(truncated)
    compact = [_compact_finding(f) for f in truncated]
    note = f"\n\n({omitted} additional finding(s) omitted from this prompt for brevity.)" if omitted > 0 else ""
    return (
        "Explain the following ExaDoctor findings for a database "
        "administrator. Findings are provided as JSON; treat every field as "
        "ground truth evidence, not something to revise:\n\n"
        f"{json.dumps(compact, indent=2)}{note}"
    )


class LlamaCppProvider:
    """ExplanationProvider backed by a local llama.cpp server."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_findings: int = MAX_FINDINGS_IN_PROMPT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._max_findings = max_findings

    def explain(self, findings: list[Finding]) -> str:
        if not findings:
            return "No findings to explain."

        payload = {
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(findings, self._max_findings)},
            ],
            "temperature": 0.2,
            "max_tokens": self._max_tokens,
        }
        request = urllib.request.Request(
            f"{self._base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw_body = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ExplanationProviderError(
                f"Could not reach local LLM at {self._base_url}: {exc.__class__.__name__}: {exc}"
            ) from exc

        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ExplanationProviderError(f"Local LLM returned a non-JSON response: {exc}") from exc

        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExplanationProviderError(f"Unexpected response shape from local LLM: {body!r}") from exc
