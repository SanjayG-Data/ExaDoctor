"""Collector for EXA_SQL_DAILY (daily-aggregated SQL workload volume).

Unlike EXA_SQL_LAST_DAY (one row per statement, 24h rolling window), this
table holds one row per (day, cluster, command_name, command_class,
success, execution_mode) *group* -- e.g. "284 SELECTs succeeded on
2026-08-24, averaging 0.025s each" -- and, like EXA_DB_SIZE_DAILY/
EXA_MONITOR_DAILY, accumulates indefinitely rather than rolling off after
24 hours, so it needs the same explicit window to avoid an unbounded scan.

Only COUNT and DURATION_AVG are selected -- the two inputs SQL-WORKLOAD-
TREND-001 actually needs to derive daily statement volume and total
execution time. The table also carries per-group CPU/I/O/row-count
averages, more query-profile-level detail not yet needed here -- narrowing
the SELECT list, same discipline as every other collector here.
"""

from __future__ import annotations

from exadoctor.collectors.base import run_bounded_collector
from exadoctor.collectors.models import CollectionResult, SqlDailySample
from exadoctor.connection.gateway import SqlGateway

DEFAULT_WINDOW_DAYS = 90


def _row_factory(row: tuple) -> SqlDailySample:
    (
        cluster_name,
        interval_start,
        command_name,
        command_class,
        success,
        count,
        duration_avg,
    ) = row
    return SqlDailySample(
        cluster_name=cluster_name,
        interval_start=interval_start,
        command_name=command_name,
        command_class=command_class,
        success=bool(success),
        count=int(count),
        duration_avg_seconds=float(duration_avg) if duration_avg is not None else None,
    )


def collect_sql_daily(gateway: SqlGateway, window_days: int = DEFAULT_WINDOW_DAYS) -> CollectionResult[SqlDailySample]:
    if window_days <= 0:
        raise ValueError("window_days must be positive")

    # window_days is coerced to int before interpolation, so this cannot
    # carry SQL metacharacters regardless of caller input.
    sql = (
        'SELECT "CLUSTER_NAME", "INTERVAL_START", "COMMAND_NAME", "COMMAND_CLASS", "SUCCESS", "COUNT", "DURATION_AVG" '
        'FROM "EXA_STATISTICS"."EXA_SQL_DAILY" '
        f"WHERE \"INTERVAL_START\" >= CURRENT_DATE - INTERVAL '{int(window_days)}' DAY"
    )
    return run_bounded_collector(gateway, source_id="EXA_SQL_DAILY", sql=sql, row_factory=_row_factory)
