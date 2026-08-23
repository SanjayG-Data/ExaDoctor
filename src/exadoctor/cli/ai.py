"""Shared `--explain` flag handling for CLI commands.

A failing or unconfigured AI layer must never break the deterministic
report -- `maybe_explain` never raises; it always returns either the
explanation text or a clear human-readable reason one isn't available.
"""

from __future__ import annotations

import click

from exadoctor.errors import ConfigurationError, ExplanationProviderError
from exadoctor.explain.factory import get_provider
from exadoctor.models.finding import Finding


def maybe_explain(findings: list[Finding], enabled: bool) -> str | None:
    """Returns None if --explain wasn't requested at all (the report then
    has no AI section, per render_*_text/html's own None-means-omit
    handling). If requested, always returns a string."""
    if not enabled:
        return None

    try:
        provider = get_provider()
    except ConfigurationError as exc:
        return f"AI explanation requested but misconfigured: {exc}"

    if provider is None:
        return (
            "AI explanation requested, but no provider is configured. "
            "Set EXADOCTOR_LLM_PROVIDER=local (and optionally EXADOCTOR_LLM_BASE_URL) to enable it."
        )

    click.echo(
        "Generating AI explanation via the local LLM (this can take several minutes on CPU-only hardware)...",
        err=True,
    )
    try:
        return provider.explain(findings)
    except ExplanationProviderError as exc:
        return f"AI explanation unavailable: {exc}"
