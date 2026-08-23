"""Typed error hierarchy for ExaDoctor.

Collectors catch `ExaDoctorError` subclasses to degrade a single source
gracefully (recording NOT_EVALUATED) instead of letting one failure abort
the whole scan. Unexpected exceptions are left to propagate.
"""

from __future__ import annotations


class ExaDoctorError(Exception):
    """Base class for all errors ExaDoctor raises intentionally."""


class ConfigurationError(ExaDoctorError):
    """Connection configuration is missing or invalid."""


class ConnectionFailedError(ExaDoctorError):
    """A connection to Exasol could not be established.

    Messages must never include the password that was used to connect.
    """


class NonReadOnlyStatementError(ExaDoctorError):
    """A caller attempted to run a non-SELECT statement through the
    read-only gateway."""


class SourceUnavailableError(ExaDoctorError):
    """A required source, column, or privilege is not available.

    Callers should catch this and record NOT_EVALUATED rather than let it
    abort the wider scan.
    """


class BaselineNotFoundError(ExaDoctorError):
    """A requested named baseline does not exist in the local baseline store."""


class ExplanationProviderError(ExaDoctorError):
    """An AI explanation provider could not be reached or returned an
    unexpected response. Never fatal to the core tool -- callers must catch
    this and report the AI layer as unavailable, not abort the scan/query."""


class OutputWriteError(ExaDoctorError):
    """A local filesystem operation (writing a report, opening/creating the
    baseline store) failed. Found by independent QA: `--output <bad path>`
    and an unwritable EXADOCTOR_BASELINE_DB location previously raised a
    raw FileNotFoundError/OSError straight through main() -- a full Python
    traceback for an ordinary user typo, contradicting this tool's own
    "every command prints a sanitized, actionable error, never a
    traceback" guarantee. Every filesystem touch point must wrap its
    exception in this before it reaches the CLI layer."""
