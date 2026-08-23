"""Shared Snapshot-building helper for rule tests (not itself a test module)."""

from __future__ import annotations

from datetime import datetime

from exadoctor.collectors.models import (
    CollectionResult,
    DbSizeDailySample,
    MetadataProperty,
    MonitorSample,
    Parameter,
    SessionInfo,
    SqlStatement,
    UsageSample,
)
from exadoctor.models.snapshot import DatabaseInfo, Snapshot

DB_TIME = datetime(2026, 8, 22, 13, 0, 0)


def _empty(source_id: str) -> CollectionResult:
    return CollectionResult(source_id=source_id, stability="PUBLIC", available=True, reason=None, rows=[])


def _unavailable(source_id: str, reason: str = "simulated unavailable") -> CollectionResult:
    return CollectionResult(source_id=source_id, stability="PUBLIC", available=False, reason=reason, rows=[])


def make_snapshot(
    *,
    monitoring: CollectionResult[MonitorSample] | None = None,
    workload: CollectionResult[SqlStatement] | None = None,
    storage: CollectionResult[DbSizeDailySample] | None = None,
    sessions: CollectionResult[SessionInfo] | None = None,
    database_time: datetime | None = DB_TIME,
) -> Snapshot:
    return Snapshot(
        database=DatabaseInfo(host="localhost", port=8564, version="2026.1.0"),
        database_time=database_time,
        capabilities=[],
        metadata=_empty("EXA_METADATA"),
        parameters=_empty("EXA_PARAMETERS"),
        sessions=sessions if sessions is not None else _empty("EXA_ALL_SESSIONS"),
        workload=workload if workload is not None else _empty("EXA_SQL_LAST_DAY"),
        monitoring=monitoring if monitoring is not None else _empty("EXA_MONITOR_LAST_DAY"),
        storage=storage if storage is not None else _empty("EXA_DB_SIZE_DAILY"),
        usage=_empty("EXA_USAGE_LAST_DAY"),
    )


def unavailable_monitoring() -> CollectionResult[MonitorSample]:
    return _unavailable("EXA_MONITOR_LAST_DAY")


def unavailable_workload() -> CollectionResult[SqlStatement]:
    return _unavailable("EXA_SQL_LAST_DAY")


def unavailable_storage() -> CollectionResult[DbSizeDailySample]:
    return _unavailable("EXA_DB_SIZE_DAILY")


def unavailable_sessions() -> CollectionResult[SessionInfo]:
    return _unavailable("EXA_ALL_SESSIONS")


def monitor_sample(measure_time: datetime, **kwargs) -> MonitorSample:
    defaults = dict(
        cluster_name="MAIN",
        measure_time=measure_time,
        load=0.1,
        cpu_percent=1.0,
        temp_db_ram_mib=10.0,
        persistent_db_ram_mib=0.0,
        net_mib_per_sec=0.0,
        swap_mib_per_sec=0.0,
    )
    defaults.update(kwargs)
    return MonitorSample(**defaults)


def sql_statement(session_id: int, stmt_id: int, **kwargs) -> SqlStatement:
    defaults = dict(
        session_id=session_id,
        stmt_id=stmt_id,
        command_name="SELECT",
        command_class="DQL",
        duration_seconds=0.1,
        start_time=datetime(2026, 8, 22, 12, 0, 0),
        stop_time=datetime(2026, 8, 22, 12, 0, 1),
        cpu_percent=1.0,
        temp_db_ram_peak_mib=0.0,
        local_read_size_mib=0.0,
        remote_read_size_mib=0.0,
        net_mib_per_sec=0.0,
        success=True,
        error_code=None,
        error_text=None,
        row_count=1,
        cluster_name="MAIN",
    )
    defaults.update(kwargs)
    return SqlStatement(**defaults)


def db_size_sample(interval_start: datetime, **kwargs) -> DbSizeDailySample:
    defaults = dict(
        cluster_name="MAIN",
        interval_start=interval_start,
        storage_size_avg_gib=10.0,
        storage_size_max_gib=10.0,
        use_avg_percent=1.0,
        use_max_percent=1.0,
        recommended_db_ram_size_avg_gib=2.0,
        object_count_avg=10.0,
    )
    defaults.update(kwargs)
    return DbSizeDailySample(**defaults)


def session_info(session_id: int, **kwargs) -> SessionInfo:
    defaults = dict(
        session_id=session_id,
        user_name="SYS",
        status="IDLE",
        command_name=None,
        stmt_id=None,
        duration_seconds=1.0,
        login_time=datetime(2026, 8, 22, 12, 0, 0),
        temp_db_ram_mib=1.0,
        persistent_db_ram_mib=0.0,
        consumer_group=None,
        cluster_name="MAIN",
    )
    defaults.update(kwargs)
    return SessionInfo(**defaults)
