"""Collector for EXA_SQL_LAST_DAY (executed SQL statements, last 24 hours)."""

from __future__ import annotations

from exadoctor.collectors.base import run_bounded_collector
from exadoctor.collectors.models import CollectionResult, SqlStatement
from exadoctor.connection.gateway import SqlGateway

COLUMNS = (
    "SESSION_ID",
    "STMT_ID",
    "COMMAND_NAME",
    "COMMAND_CLASS",
    "DURATION",
    "START_TIME",
    "STOP_TIME",
    "CPU",
    "TEMP_DB_RAM_PEAK",
    "LOCAL_READ_SIZE",
    "REMOTE_READ_SIZE",
    "NET",
    "SUCCESS",
    "ERROR_CODE",
    "ERROR_TEXT",
    "ROW_COUNT",
    "CLUSTER_NAME",
)

SQL = 'SELECT {} FROM "EXA_STATISTICS"."EXA_SQL_LAST_DAY"'.format(", ".join(f'"{c}"' for c in COLUMNS))


def row_to_sql_statement(row: tuple) -> SqlStatement:
    """Map a raw row in `COLUMNS` order to a SqlStatement.

    Public (not just used by the bulk collector below) so the query
    analyzer's single-row, SESSION_ID/STMT_ID-filtered lookup can reuse the
    exact same mapping instead of duplicating it.
    """
    (
        session_id,
        stmt_id,
        command_name,
        command_class,
        duration,
        start_time,
        stop_time,
        cpu,
        temp_db_ram_peak,
        local_read_size,
        remote_read_size,
        net,
        success,
        error_code,
        error_text,
        row_count,
        cluster_name,
    ) = row
    return SqlStatement(
        session_id=session_id,
        stmt_id=stmt_id,
        command_name=command_name,
        command_class=command_class,
        duration_seconds=float(duration) if duration is not None else None,
        start_time=start_time,
        stop_time=stop_time,
        cpu_percent=float(cpu) if cpu is not None else None,
        temp_db_ram_peak_mib=float(temp_db_ram_peak) if temp_db_ram_peak is not None else None,
        local_read_size_mib=float(local_read_size) if local_read_size is not None else None,
        remote_read_size_mib=float(remote_read_size) if remote_read_size is not None else None,
        net_mib_per_sec=float(net) if net is not None else None,
        success=bool(success),
        error_code=error_code,
        error_text=error_text,
        row_count=row_count,
        cluster_name=cluster_name,
    )


def collect_sql_last_day(gateway: SqlGateway) -> CollectionResult[SqlStatement]:
    return run_bounded_collector(gateway, source_id="EXA_SQL_LAST_DAY", sql=SQL, row_factory=row_to_sql_statement)
