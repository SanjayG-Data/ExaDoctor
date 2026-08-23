"""Live capability probing against a connected ReadOnlyGateway.

Existence and privilege failures are not distinguished by parsing Exasol
error text: a live check confirmed Exasol returns the same generic
"object X not found" message for a missing table and a missing column, so
any attempt to classify the *cause* from that text would be guessing at
undocumented behavior. Instead, probing is tiered so the actual SQL
outcome -- not error-message parsing -- determines what is reported:

1. Whole-table access check (`SELECT COUNT(*) FROM <source>`).
2. Bulk required-columns check in one round trip.
3. Only if (2) fails: a per-column fallback to identify exactly which
   columns are missing.
"""

from __future__ import annotations

from datetime import datetime

from exadoctor.capabilities.models import Capability
from exadoctor.capabilities.sources import SourceSpec
from exadoctor.connection.gateway import SqlGateway
from exadoctor.errors import ExaDoctorError

_MAX_REASON_LENGTH = 300


def _sanitized_reason(exc: Exception) -> str:
    message = str(exc).strip().replace("\n", " ")
    if len(message) > _MAX_REASON_LENGTH:
        message = message[:_MAX_REASON_LENGTH] + "..."
    return f"{exc.__class__.__name__}: {message}"


def _table_row_count(gateway: SqlGateway, spec: SourceSpec) -> tuple[int, None] | tuple[None, str]:
    try:
        result = gateway.execute(f"SELECT COUNT(*) AS ROW_COUNT FROM {spec.qualified_name}")
        return int(result.rows[0][0]) if result.rows else 0, None
    except ExaDoctorError as exc:
        return None, _sanitized_reason(exc)


def _bulk_columns_available(gateway: SqlGateway, spec: SourceSpec) -> bool:
    columns_clause = ", ".join(f'"{c}"' for c in spec.required_columns)
    try:
        gateway.execute(
            f"SELECT COUNT(*) AS ROW_COUNT FROM "
            f"(SELECT {columns_clause} FROM {spec.qualified_name}) AS PROBE"
        )
        return True
    except ExaDoctorError:
        return False


def _column_available(gateway: SqlGateway, spec: SourceSpec, column: str) -> bool:
    try:
        gateway.execute(f'SELECT "{column}" FROM {spec.qualified_name} LIMIT 1')
        return True
    except ExaDoctorError:
        return False


def probe_database_version(gateway: SqlGateway) -> str | None:
    try:
        result = gateway.execute(
            'SELECT "PARAM_VALUE" FROM "SYS"."EXA_METADATA" '
            "WHERE \"PARAM_NAME\" = 'databaseProductVersion'"
        )
        return str(result.rows[0][0]) if result.rows else None
    except ExaDoctorError:
        return None


def probe_database_time(gateway: SqlGateway) -> datetime | None:
    """The database's own current time -- used as the reference clock for
    any rule computing an age/duration against a DB-sourced timestamp
    (e.g. session age from LOGIN_TIME), so it never has to compare against
    this process's local wall clock across a possible timezone/clock-skew
    mismatch with the Exasol server.

    CURRENT_TIMESTAMP's wire type is "TIMESTAMP WITH LOCAL TIME ZONE",
    which pyexasol's bundled mapper does not convert (confirmed live) --
    unlike a plain TIMESTAMP column it falls through to a raw string. The
    explicit CAST forces the plain TIMESTAMP wire type instead.
    """
    try:
        result = gateway.execute("SELECT CAST(CURRENT_TIMESTAMP AS TIMESTAMP) AS DB_TIME")
        return result.rows[0][0] if result.rows else None
    except ExaDoctorError:
        return None


def probe_source(gateway: SqlGateway, spec: SourceSpec, database_version: str | None) -> Capability:
    row_count, reason = _table_row_count(gateway, spec)
    if row_count is None:
        return Capability(
            id=spec.id,
            available=False,
            reason=reason,
            source=spec.qualified_name,
            stability="PUBLIC",
            database_version=database_version,
            privilege_required=spec.privilege_required,
            detected_columns=[],
            missing_columns=list(spec.required_columns),
            data_available=None,
        )

    if _bulk_columns_available(gateway, spec):
        detected = list(spec.required_columns)
        missing: list[str] = []
    else:
        detected = [c for c in spec.required_columns if _column_available(gateway, spec, c)]
        missing = [c for c in spec.required_columns if c not in detected]

    return Capability(
        id=spec.id,
        available=not missing,
        reason=None if not missing else f"Missing required columns: {', '.join(missing)}",
        source=spec.qualified_name,
        stability="PUBLIC",
        database_version=database_version,
        privilege_required=spec.privilege_required,
        detected_columns=detected,
        missing_columns=missing,
        data_available=row_count > 0,
    )


def probe_all(gateway: SqlGateway, specs: tuple[SourceSpec, ...]) -> tuple[str | None, list[Capability]]:
    """Probe every source independently -- one failure must never abort the rest."""
    database_version = probe_database_version(gateway)
    capabilities: list[Capability] = []
    for spec in specs:
        try:
            capabilities.append(probe_source(gateway, spec, database_version))
        except Exception as exc:  # noqa: BLE001 - a single source must never abort the probe run
            capabilities.append(
                Capability(
                    id=spec.id,
                    available=False,
                    reason=_sanitized_reason(exc),
                    source=spec.qualified_name,
                    stability="PUBLIC",
                    database_version=database_version,
                    privilege_required=spec.privilege_required,
                    detected_columns=[],
                    missing_columns=list(spec.required_columns),
                    data_available=None,
                )
            )
    return database_version, capabilities
