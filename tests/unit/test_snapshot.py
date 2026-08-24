"""Unit tests for the Snapshot model: JSON round-trip and secret-safety."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from exadoctor.capabilities.models import Capability
from exadoctor.models.finding import Evidence, Finding, FindingStatus
from exadoctor.collectors.models import (
    CollectionResult,
    MetadataProperty,
    MonitorSample,
    Parameter,
    SessionHistoryRecord,
    SessionInfo,
    SqlDailySample,
    SqlStatement,
    SystemEvent,
    TransactionConflict,
    UsageSample,
)
from exadoctor.models.snapshot import SCHEMA_VERSION, DatabaseInfo, Snapshot

SECRET_PASSWORD = "definitely-not-in-the-snapshot"


def _sample_snapshot() -> Snapshot:
    capability = Capability(
        id="EXA_METADATA",
        available=True,
        reason=None,
        source='"SYS"."EXA_METADATA"',
        stability="PUBLIC",
        database_version="2026.1.0",
        privilege_required=None,
        detected_columns=["PARAM_NAME", "PARAM_VALUE"],
        missing_columns=[],
        data_available=True,
        detected_at=datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc),
    )

    metadata = CollectionResult(
        source_id="EXA_METADATA",
        stability="PUBLIC",
        available=True,
        reason=None,
        rows=[MetadataProperty(param_name="databaseProductVersion", param_value="2026.1.0")],
        collected_at=datetime(2026, 8, 22, 12, 0, 1, tzinfo=timezone.utc),
    )
    parameters = CollectionResult(
        source_id="EXA_PARAMETERS",
        stability="PUBLIC",
        available=True,
        reason=None,
        rows=[Parameter(parameter_name="NLS_DATE_FORMAT", session_value="YYYY-MM-DD", system_value="YYYY-MM-DD")],
    )
    sessions = CollectionResult(
        source_id="EXA_ALL_SESSIONS",
        stability="PUBLIC",
        available=True,
        reason=None,
        rows=[
            SessionInfo(
                session_id=4,
                user_name="SYS",
                status="IDLE",
                command_name=None,
                stmt_id=None,
                duration_seconds=41.0,
                login_time=datetime(2026, 8, 22, 11, 48, 15, 789000),  # naive: real Exasol TIMESTAMP values carry no tzinfo
                temp_db_ram_mib=66.9,
                persistent_db_ram_mib=0.0,
                consumer_group="SYS_CONSUMER_GROUP",
                cluster_name="MAIN",
            )
        ],
    )
    session_history = CollectionResult(
        source_id="EXA_DBA_SESSIONS_LAST_DAY",
        stability="PUBLIC",
        available=True,
        reason=None,
        rows=[
            SessionHistoryRecord(
                session_id=1874216507191132160,
                login_time=datetime(2026, 8, 22, 11, 49, 6, 292000),  # naive: real Exasol TIMESTAMP
                logout_time=datetime(2026, 8, 23, 11, 49, 7, 54000),  # naive: real Exasol TIMESTAMP
                user_name="SYS",
                host="127.0.0.1",
                success=True,
                error_code="R0033",
                error_text="Connection lost after idle timeout.",
                cluster_name="MAIN",
            )
        ],
    )
    workload = CollectionResult(
        source_id="EXA_SQL_LAST_DAY",
        stability="PUBLIC",
        available=True,
        reason=None,
        rows=[
            SqlStatement(
                session_id=1874035687682015232,
                stmt_id=133,
                command_name="ROLLBACK",
                command_class="TRANSACTION",
                duration_seconds=0.002,
                start_time=datetime(2026, 8, 21, 13, 43, 52, 697000),  # naive: real Exasol TIMESTAMP
                stop_time=datetime(2026, 8, 21, 13, 43, 52, 699000),  # naive: real Exasol TIMESTAMP
                cpu_percent=4.5,
                temp_db_ram_peak_mib=13.4,
                local_read_size_mib=0.0,
                remote_read_size_mib=0.0,
                net_mib_per_sec=0.0,
                success=True,
                error_code=None,
                error_text=None,
                row_count=0,
                cluster_name="MAIN",
            )
        ],
    )
    sql_daily = CollectionResult(
        source_id="EXA_SQL_DAILY",
        stability="PUBLIC",
        available=True,
        reason=None,
        rows=[
            SqlDailySample(
                cluster_name="MAIN",
                interval_start=datetime(2026, 8, 24, 0, 0),  # naive: real Exasol TIMESTAMP
                command_name="SELECT",
                command_class="DQL",
                success=True,
                count=284,
                duration_avg_seconds=0.025,
            )
        ],
    )
    monitoring = CollectionResult(
        source_id="EXA_MONITOR_LAST_DAY",
        stability="PUBLIC",
        available=True,
        reason=None,
        rows=[
            MonitorSample(
                cluster_name="MAIN",
                measure_time=datetime(2026, 8, 21, 13, 0),  # naive: real Exasol TIMESTAMP
                load=0.2,
                cpu_percent=0.2,
                temp_db_ram_mib=493.9,
                persistent_db_ram_mib=0.0,
                net_mib_per_sec=0.0,
                swap_mib_per_sec=0.0,
            )
        ],
    )
    monitor_daily = CollectionResult(
        source_id="EXA_MONITOR_DAILY", stability="PUBLIC", available=True, reason=None, rows=[]
    )
    storage = CollectionResult(source_id="EXA_DB_SIZE_DAILY", stability="PUBLIC", available=True, reason=None, rows=[])
    usage = CollectionResult(
        source_id="EXA_USAGE_LAST_DAY",
        stability="PUBLIC",
        available=True,
        reason=None,
        rows=[UsageSample(cluster_name="MAIN", measure_time=datetime(2026, 8, 21, 13, 0), users=1, queries=0)],  # naive: real Exasol TIMESTAMP
    )
    system_events = CollectionResult(
        source_id="EXA_SYSTEM_EVENTS",
        stability="PUBLIC",
        available=True,
        reason=None,
        rows=[
            SystemEvent(
                cluster_name="MAIN",
                measure_time=datetime(2026, 8, 22, 11, 48, 15, 908000),  # naive: real Exasol TIMESTAMP
                event_type="STARTUP",
                dbms_version="2026.1.0",
                nodes=1,
                db_ram_size_gib=2.0,
                vcpu=22,
            )
        ],
    )

    transaction_conflicts = CollectionResult(
        source_id="EXA_DBA_TRANSACTION_CONFLICTS",
        stability="PUBLIC",
        available=True,
        reason=None,
        rows=[
            TransactionConflict(
                session_id=1870936279216291840,
                conflict_session_id=1870936279003561984,
                start_time=datetime(2026, 8, 22, 11, 32, 1, 246000),  # naive: real Exasol TIMESTAMP
                stop_time=datetime(2026, 8, 22, 11, 32, 1, 280000),  # naive: real Exasol TIMESTAMP
                conflict_type="WAIT FOR COMMIT",
                conflict_objects="MARKET.SIGNALS",
                conflict_info=None,
            )
        ],
    )

    return Snapshot(
        database=DatabaseInfo(host="localhost", port=8564, version="2026.1.0"),
        capabilities=[capability],
        metadata=metadata,
        parameters=parameters,
        sessions=sessions,
        session_history=session_history,
        workload=workload,
        sql_daily=sql_daily,
        monitoring=monitoring,
        monitor_daily=monitor_daily,
        storage=storage,
        usage=usage,
        system_events=system_events,
        transaction_conflicts=transaction_conflicts,
        collection_time=datetime(2026, 8, 22, 12, 0, 2, tzinfo=timezone.utc),
        database_time=datetime(2026, 8, 22, 12, 0, 1, 500000),  # naive: Exasol server civil time
        findings=[
            Finding(
                id="SYS-SWAP-001",
                title="Swap activity detected",
                category="system",
                status=FindingStatus.WARNING,
                summary="Swap observed",
                evidence=[
                    Evidence(
                        source="EXA_MONITOR_LAST_DAY",
                        stability="PUBLIC",
                        metric="SWAP",
                        value=0.4,
                        unit="MiB/s",
                        timestamp=datetime(2026, 8, 21, 13, 41, 30),
                    )
                ],
            )
        ],
    )


def test_schema_version_is_explicit() -> None:
    snapshot = _sample_snapshot()
    assert snapshot.schema_version == SCHEMA_VERSION
    assert snapshot.to_dict()["schema_version"] == SCHEMA_VERSION


def test_snapshot_round_trips_through_json() -> None:
    original = _sample_snapshot()
    payload = json.dumps(original.to_dict())
    restored = Snapshot.from_dict(json.loads(payload))

    assert restored == original


def test_snapshot_never_contains_credentials() -> None:
    snapshot = _sample_snapshot()
    payload = json.dumps(snapshot.to_dict())

    assert SECRET_PASSWORD not in payload
    assert '"password"' not in payload
    assert '"user":' not in payload  # DatabaseInfo carries host/port/version only


def test_database_info_has_no_credential_fields() -> None:
    field_names = {f.name for f in DatabaseInfo.__dataclass_fields__.values()}
    assert field_names == {"host", "port", "version"}
