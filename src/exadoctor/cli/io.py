"""Shared filesystem helpers for CLI commands.

Every filesystem touch point a command exposes to the user (an --output
path, the baseline SQLite location) must go through something like this,
wrapping the raw OSError/FileNotFoundError/etc. into an `ExaDoctorError` so
`handle_exadoctor_errors` can turn it into the same sanitized, actionable
message every other failure gets -- found missing here by independent QA:
an ordinary typo'd --output directory was dumping a full Python traceback,
contradicting the tool's own "never a traceback" guarantee.
"""

from __future__ import annotations

from pathlib import Path

from exadoctor.errors import OutputWriteError


def write_report_output(path: str, content: str) -> None:
    try:
        Path(path).write_text(content, encoding="utf-8")
    except OSError as exc:
        raise OutputWriteError(f"Could not write report to {path!r}: {exc.__class__.__name__}: {exc}") from exc
