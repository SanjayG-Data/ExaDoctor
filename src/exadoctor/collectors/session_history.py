"""Collector for EXA_DBA_SESSIONS_LAST_DAY (login/logout history, including
sessions that have already ended -- something EXA_ALL_SESSIONS/EXA_DBA_
SESSIONS structurally cannot show since they only list currently-open
sessions).

Genuinely a `_LAST_DAY` table (Exasol's own 24h rolling window, like
EXA_SQL_LAST_DAY/EXA_MONITOR_LAST_DAY) -- no explicit window needed here,
unlike EXA_DB_SIZE_DAILY/EXA_DBA_TRANSACTION_CONFLICTS/EXA_MONITOR_DAILY
which accumulate indefinitely.
"""

from __future__ import annotations

from exadoctor.collectors.base import run_bounded_collector
from exadoctor.collectors.models import CollectionResult, SessionHistoryRecord
from exadoctor.connection.gateway import SqlGateway

SQL = (
    'SELECT "SESSION_ID", "LOGIN_TIME", "LOGOUT_TIME", "USER_NAME", "HOST", '
    '"SUCCESS", "ERROR_CODE", "ERROR_TEXT", "CLUSTER_NAME" '
    'FROM "EXA_STATISTICS"."EXA_DBA_SESSIONS_LAST_DAY"'
)


def _row_factory(row: tuple) -> SessionHistoryRecord:
    (
        session_id,
        login_time,
        logout_time,
        user_name,
        host,
        success,
        error_code,
        error_text,
        cluster_name,
    ) = row
    return SessionHistoryRecord(
        session_id=session_id,
        login_time=login_time,
        logout_time=logout_time,
        user_name=user_name,
        host=host,
        success=bool(success),
        error_code=error_code,
        error_text=error_text,
        cluster_name=cluster_name,
    )


def collect_session_history(gateway: SqlGateway) -> CollectionResult[SessionHistoryRecord]:
    return run_bounded_collector(gateway, source_id="EXA_DBA_SESSIONS_LAST_DAY", sql=SQL, row_factory=_row_factory)
