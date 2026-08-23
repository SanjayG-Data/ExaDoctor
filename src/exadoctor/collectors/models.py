"""Normalized row models produced by public collectors.

Numeric metrics (CPU%, memory MiB, durations, throughput) are stored as
`float` -- diagnostic thresholds and percentiles don't need Decimal
exactness, and float avoids JSON/Decimal serialization friction. Identifiers
and exact counts (SESSION_ID, STMT_ID, ROW_COUNT) stay `int`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Generic, TypeVar


def json_safe(value: Any) -> Any:
    """Recursively convert Decimal/datetime/date/dataclasses into JSON-safe
    values. Public: reused wherever a single row dataclass (not just a
    CollectionResult) needs ad hoc serialization, e.g. the query analyzer."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: json_safe(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    return value


def _parse_iso_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


T = TypeVar("T")


@dataclass
class CollectionResult(Generic[T]):
    source_id: str
    stability: str
    available: bool
    reason: str | None
    rows: list[T] = field(default_factory=list)
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "stability": self.stability,
            "available": self.available,
            "reason": self.reason,
            "row_count": len(self.rows),
            "collected_at": self.collected_at.isoformat(),
            "rows": [json_safe(row) for row in self.rows],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], row_cls: type[T]) -> CollectionResult[T]:
        return cls(
            source_id=data["source_id"],
            stability=data["stability"],
            available=data["available"],
            reason=data["reason"],
            rows=[row_cls.from_dict(r) for r in data["rows"]],  # type: ignore[attr-defined]
            collected_at=datetime.fromisoformat(data["collected_at"]),
        )


@dataclass
class MetadataProperty:
    param_name: str
    param_value: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetadataProperty:
        return cls(param_name=data["param_name"], param_value=data["param_value"])


@dataclass
class Parameter:
    parameter_name: str
    session_value: str | None
    system_value: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Parameter:
        return cls(
            parameter_name=data["parameter_name"],
            session_value=data["session_value"],
            system_value=data["system_value"],
        )


@dataclass
class SessionInfo:
    session_id: int
    user_name: str
    status: str
    command_name: str | None
    stmt_id: int | None
    duration_seconds: float | None
    login_time: datetime | None
    temp_db_ram_mib: float | None
    persistent_db_ram_mib: float | None
    consumer_group: str | None
    cluster_name: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionInfo:
        return cls(
            session_id=data["session_id"],
            user_name=data["user_name"],
            status=data["status"],
            command_name=data["command_name"],
            stmt_id=data["stmt_id"],
            duration_seconds=data["duration_seconds"],
            login_time=_parse_iso_datetime(data["login_time"]),
            temp_db_ram_mib=data["temp_db_ram_mib"],
            persistent_db_ram_mib=data["persistent_db_ram_mib"],
            consumer_group=data["consumer_group"],
            cluster_name=data["cluster_name"],
        )


@dataclass
class SqlStatement:
    session_id: int
    stmt_id: int
    command_name: str
    command_class: str | None
    duration_seconds: float | None
    start_time: datetime | None
    stop_time: datetime | None
    cpu_percent: float | None
    temp_db_ram_peak_mib: float | None
    local_read_size_mib: float | None
    remote_read_size_mib: float | None
    net_mib_per_sec: float | None
    success: bool
    error_code: str | None
    error_text: str | None
    row_count: int | None
    cluster_name: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SqlStatement:
        return cls(
            session_id=data["session_id"],
            stmt_id=data["stmt_id"],
            command_name=data["command_name"],
            command_class=data["command_class"],
            duration_seconds=data["duration_seconds"],
            start_time=_parse_iso_datetime(data["start_time"]),
            stop_time=_parse_iso_datetime(data["stop_time"]),
            cpu_percent=data["cpu_percent"],
            temp_db_ram_peak_mib=data["temp_db_ram_peak_mib"],
            local_read_size_mib=data["local_read_size_mib"],
            remote_read_size_mib=data["remote_read_size_mib"],
            net_mib_per_sec=data["net_mib_per_sec"],
            success=data["success"],
            error_code=data["error_code"],
            error_text=data["error_text"],
            row_count=data["row_count"],
            cluster_name=data["cluster_name"],
        )


@dataclass
class MonitorSample:
    cluster_name: str | None
    measure_time: datetime
    load: float | None
    cpu_percent: float | None
    temp_db_ram_mib: float | None
    persistent_db_ram_mib: float | None
    net_mib_per_sec: float | None
    swap_mib_per_sec: float | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MonitorSample:
        return cls(
            cluster_name=data["cluster_name"],
            measure_time=_parse_iso_datetime(data["measure_time"]),
            load=data["load"],
            cpu_percent=data["cpu_percent"],
            temp_db_ram_mib=data["temp_db_ram_mib"],
            persistent_db_ram_mib=data["persistent_db_ram_mib"],
            net_mib_per_sec=data["net_mib_per_sec"],
            swap_mib_per_sec=data["swap_mib_per_sec"],
        )


@dataclass
class DbSizeDailySample:
    cluster_name: str | None
    interval_start: datetime
    storage_size_avg_gib: float | None
    storage_size_max_gib: float | None
    use_avg_percent: float | None
    use_max_percent: float | None
    recommended_db_ram_size_avg_gib: float | None
    object_count_avg: float | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DbSizeDailySample:
        return cls(
            cluster_name=data["cluster_name"],
            interval_start=_parse_iso_datetime(data["interval_start"]),
            storage_size_avg_gib=data["storage_size_avg_gib"],
            storage_size_max_gib=data["storage_size_max_gib"],
            use_avg_percent=data["use_avg_percent"],
            use_max_percent=data["use_max_percent"],
            recommended_db_ram_size_avg_gib=data["recommended_db_ram_size_avg_gib"],
            object_count_avg=data["object_count_avg"],
        )


@dataclass
class UsageSample:
    cluster_name: str | None
    measure_time: datetime
    users: int | None
    queries: int | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UsageSample:
        return cls(
            cluster_name=data["cluster_name"],
            measure_time=_parse_iso_datetime(data["measure_time"]),
            users=data["users"],
            queries=data["queries"],
        )
