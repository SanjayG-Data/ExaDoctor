import json
import urllib.error

import pytest

from exadoctor.errors import ExplanationProviderError
from exadoctor.explain.local_llamacpp import LlamaCppProvider
from exadoctor.models.finding import Finding, FindingStatus


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _finding() -> Finding:
    return Finding(id="SYS-SWAP-001", title="Swap detected", category="system", status=FindingStatus.WARNING, summary="Swap observed")


def test_explain_with_no_findings_short_circuits_without_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("should not make an HTTP request for an empty finding list")

    monkeypatch.setattr("urllib.request.urlopen", fail_if_called)
    provider = LlamaCppProvider()
    assert provider.explain([]) == "No findings to explain."


def test_explain_returns_message_content_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    response_body = json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": "Swap activity is worth investigating."}}]}
    ).encode("utf-8")

    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["data"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse(response_body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = LlamaCppProvider(base_url="http://localhost:8080", timeout=5.0, max_tokens=50)
    result = provider.explain([_finding()])

    assert result == "Swap activity is worth investigating."
    assert captured["url"] == "http://localhost:8080/v1/chat/completions"
    assert captured["timeout"] == 5.0
    assert captured["data"]["max_tokens"] == 50
    assert captured["data"]["messages"][0]["role"] == "system"
    assert "SYS-SWAP-001" in captured["data"]["messages"][1]["content"]


def test_explain_raises_typed_error_on_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = LlamaCppProvider()
    with pytest.raises(ExplanationProviderError, match="Could not reach local LLM"):
        provider.explain([_finding()])


def test_explain_raises_typed_error_on_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout=None):
        return _FakeResponse(b"not json")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = LlamaCppProvider()
    with pytest.raises(ExplanationProviderError, match="non-JSON"):
        provider.explain([_finding()])


def test_explain_prompt_excludes_verbose_fields_to_bound_prompt_size(monkeypatch: pytest.MonkeyPatch) -> None:
    # Real constraint, not cosmetic: this model runs at ~1 token/sec for both
    # prompt processing and generation, so sending full Finding.to_dict()
    # (evidence/limitations/documentation) for many findings would put a
    # single --explain call in the 5-10 minute range. Only the compact
    # fields should reach the prompt.
    from exadoctor.models.finding import Evidence

    finding = Finding(
        id="SQL-TEMP-001",
        title="TEMP outlier",
        category="workload",
        status=FindingStatus.WARNING,
        summary="short summary",
        evidence=[Evidence(source="EXA_SQL_LAST_DAY", stability="PUBLIC", metric="TEMP_DB_RAM_PEAK", value=999.9, unit="MiB", timestamp=None)],
        limitations=["a very specific limitation string that should not appear in the prompt"],
        documentation=["ExaDoctor policy: some very specific documentation string"],
    )
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["data"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    LlamaCppProvider().explain([finding])

    prompt = captured["data"]["messages"][1]["content"]
    assert "999.9" not in prompt  # evidence value dropped
    assert "very specific limitation" not in prompt
    assert "very specific documentation" not in prompt
    assert "SQL-TEMP-001" in prompt  # id/title/summary/recommendation kept


def test_explain_caps_number_of_findings_and_notes_omission(monkeypatch: pytest.MonkeyPatch) -> None:
    findings = [
        Finding(id=f"F-{i:03d}", title=f"title {i}", category="test", status=FindingStatus.INFO, summary=f"summary {i}")
        for i in range(20)
    ]
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["data"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = LlamaCppProvider(max_findings=5)
    provider.explain(findings)

    prompt = captured["data"]["messages"][1]["content"]
    assert "F-000" in prompt
    assert "F-004" in prompt
    assert "F-005" not in prompt
    assert "15 additional finding(s) omitted" in prompt


def test_explain_raises_typed_error_on_unexpected_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout=None):
        return _FakeResponse(json.dumps({"unexpected": "shape"}).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = LlamaCppProvider()
    with pytest.raises(ExplanationProviderError, match="Unexpected response shape"):
        provider.explain([_finding()])
