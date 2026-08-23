"""Shared collector plumbing: bounded query execution + graceful degradation.

A collector must never abort the wider scan -- a query failure degrades to
an unavailable CollectionResult, and a single malformed row is skipped
(counted, not silently dropped) rather than discarding the whole collection.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from exadoctor.collectors.models import CollectionResult
from exadoctor.connection.gateway import SqlGateway
from exadoctor.errors import ExaDoctorError

T = TypeVar("T")

_MAX_REASON_LENGTH = 300


def _sanitized_reason(exc: Exception) -> str:
    message = str(exc).strip().replace("\n", " ")
    if len(message) > _MAX_REASON_LENGTH:
        message = message[:_MAX_REASON_LENGTH] + "..."
    return f"{exc.__class__.__name__}: {message}"


def run_bounded_collector(
    gateway: SqlGateway,
    source_id: str,
    sql: str,
    row_factory: Callable[[tuple], T],
) -> CollectionResult[T]:
    try:
        result = gateway.execute(sql)
    except Exception as exc:  # noqa: BLE001 - one collector must never abort the scan
        return CollectionResult(
            source_id=source_id, stability="PUBLIC", available=False, reason=_sanitized_reason(exc)
        )

    rows: list[T] = []
    skipped = 0
    for raw_row in result.rows:
        try:
            rows.append(row_factory(raw_row))
        except (ValueError, TypeError, IndexError):
            skipped += 1

    reason = f"{skipped} row(s) skipped due to unexpected format" if skipped else None
    return CollectionResult(source_id=source_id, stability="PUBLIC", available=True, reason=reason, rows=rows)
