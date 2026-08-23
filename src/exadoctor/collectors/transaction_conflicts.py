"""Collector for EXA_DBA_TRANSACTION_CONFLICTS (lock/commit-wait contention
between sessions).

Like EXA_DB_SIZE_DAILY, this table accumulates indefinitely rather than
rolling off after 24 hours (confirmed live: 5000+ rows spanning over a
month on the test instance) -- an explicit window keeps this comparable to
EXA_SQL_LAST_DAY's own 24-hour horizon (SQL-CONFLICT-001 expresses total
conflict wait time as a share of that same window's total workload
duration) and avoids an unbounded scan.
"""

from __future__ import annotations

from exadoctor.collectors.base import run_bounded_collector
from exadoctor.collectors.models import CollectionResult, TransactionConflict
from exadoctor.connection.gateway import SqlGateway

DEFAULT_WINDOW_DAYS = 1


def _row_factory(row: tuple) -> TransactionConflict:
    (
        session_id,
        conflict_session_id,
        start_time,
        stop_time,
        conflict_type,
        conflict_objects,
        conflict_info,
    ) = row
    return TransactionConflict(
        session_id=session_id,
        conflict_session_id=conflict_session_id,
        start_time=start_time,
        stop_time=stop_time,
        conflict_type=conflict_type,
        conflict_objects=conflict_objects,
        conflict_info=conflict_info,
    )


def collect_transaction_conflicts(
    gateway: SqlGateway, window_days: int = DEFAULT_WINDOW_DAYS
) -> CollectionResult[TransactionConflict]:
    if window_days <= 0:
        raise ValueError("window_days must be positive")

    # window_days is coerced to int before interpolation, so this cannot
    # carry SQL metacharacters regardless of caller input.
    sql = (
        'SELECT "SESSION_ID", "CONFLICT_SESSION_ID", "START_TIME", "STOP_TIME", '
        '"CONFLICT_TYPE", "CONFLICT_OBJECTS", "CONFLICT_INFO" '
        'FROM "EXA_STATISTICS"."EXA_DBA_TRANSACTION_CONFLICTS" '
        f"WHERE \"START_TIME\" >= CURRENT_DATE - INTERVAL '{int(window_days)}' DAY"
    )
    return run_bounded_collector(
        gateway, source_id="EXA_DBA_TRANSACTION_CONFLICTS", sql=sql, row_factory=_row_factory
    )
