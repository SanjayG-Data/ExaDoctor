"""Collector for EXA_ALL_SESSIONS (open session information, all users)."""

from __future__ import annotations

from exadoctor.collectors.base import run_bounded_collector
from exadoctor.collectors.models import CollectionResult, SessionInfo
from exadoctor.connection.gateway import SqlGateway

SQL = (
    'SELECT "SESSION_ID", "USER_NAME", "STATUS", "COMMAND_NAME", "STMT_ID", '
    '"DURATION", "LOGIN_TIME", "TEMP_DB_RAM", "PERSISTENT_DB_RAM", '
    '"CONSUMER_GROUP", "CLUSTER_NAME" FROM "SYS"."EXA_ALL_SESSIONS"'
)


def _parse_hms_duration(text: str | None) -> float | None:
    """Parse EXA_ALL_SESSIONS.DURATION (VARCHAR "H:MM:SS", confirmed live)
    into seconds. Returns None for any unrecognized shape rather than
    failing the whole row."""
    if not text:
        return None
    parts = text.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        return None


def _row_factory(row: tuple) -> SessionInfo:
    (
        session_id,
        user_name,
        status,
        command_name,
        stmt_id,
        duration_raw,
        login_time,
        temp_db_ram,
        persistent_db_ram,
        consumer_group,
        cluster_name,
    ) = row
    return SessionInfo(
        session_id=session_id,
        user_name=user_name,
        status=status,
        command_name=command_name,
        stmt_id=stmt_id,
        duration_seconds=_parse_hms_duration(duration_raw),
        login_time=login_time,
        temp_db_ram_mib=float(temp_db_ram) if temp_db_ram is not None else None,
        persistent_db_ram_mib=float(persistent_db_ram) if persistent_db_ram is not None else None,
        consumer_group=consumer_group,
        cluster_name=cluster_name,
    )


def collect_sessions(gateway: SqlGateway) -> CollectionResult[SessionInfo]:
    return run_bounded_collector(gateway, source_id="EXA_ALL_SESSIONS", sql=SQL, row_factory=_row_factory)
