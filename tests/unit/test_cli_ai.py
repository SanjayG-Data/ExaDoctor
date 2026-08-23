import pytest

from exadoctor.cli.ai import maybe_explain
from exadoctor.errors import ExplanationProviderError
from exadoctor.models.finding import Finding, FindingStatus


def _finding() -> Finding:
    return Finding(id="X-001", title="t", category="c", status=FindingStatus.INFO, summary="s")


def test_maybe_explain_returns_none_when_not_enabled() -> None:
    assert maybe_explain([_finding()], enabled=False) is None


def test_maybe_explain_reports_missing_provider_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXADOCTOR_LLM_PROVIDER", raising=False)
    result = maybe_explain([_finding()], enabled=True)
    assert result is not None
    assert "no provider is configured" in result


def test_maybe_explain_reports_misconfiguration_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXADOCTOR_LLM_PROVIDER", "not-a-real-provider")
    result = maybe_explain([_finding()], enabled=True)
    assert result is not None
    assert "misconfigured" in result


def test_maybe_explain_reports_provider_failure_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingProvider:
        def explain(self, findings):
            raise ExplanationProviderError("could not reach server")

    monkeypatch.setattr("exadoctor.cli.ai.get_provider", lambda: FailingProvider())
    result = maybe_explain([_finding()], enabled=True)
    assert result is not None
    assert "AI explanation unavailable" in result
    assert "could not reach server" in result


def test_maybe_explain_returns_provider_output_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class WorkingProvider:
        def explain(self, findings):
            return "a real explanation"

    monkeypatch.setattr("exadoctor.cli.ai.get_provider", lambda: WorkingProvider())
    result = maybe_explain([_finding()], enabled=True)
    assert result == "a real explanation"
