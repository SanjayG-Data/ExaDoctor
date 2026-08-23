"""Normalized Snapshot model (roadmap section 6.5).

This is the only object diagnostic rules ever read. Rules must never query
EXA_* tables directly -- collectors/adapters translate raw Exasol sources
into this stable contract, which is what lets the product survive schema
changes in the underlying sources.

`DatabaseInfo` deliberately carries only host/port/version -- never
credentials -- so a Snapshot is structurally incapable of leaking a
password even if serialized and shared (roadmap section 12.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from exadoctor.capabilities.models import Capability
from exadoctor.capabilities.probe import probe_all, probe_database_time
from exadoctor.capabilities.sources import PUBLIC_SOURCES
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
from exadoctor.collectors.orchestrator import collect_all
from exadoctor.connection.gateway import SqlGateway
from exadoctor.models.finding import Finding

SCHEMA_VERSION = "0.1.0"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class DatabaseInfo:
    host: str
    port: int
    version: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"host": self.host, "port": self.port, "version": self.version}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatabaseInfo:
        return cls(host=data["host"], port=data["port"], version=data["version"])


@dataclass
class Snapshot:
    database: DatabaseInfo
    capabilities: list[Capability]
    metadata: CollectionResult[MetadataProperty]
    parameters: CollectionResult[Parameter]
    sessions: CollectionResult[SessionInfo]
    workload: CollectionResult[SqlStatement]
    monitoring: CollectionResult[MonitorSample]
    storage: CollectionResult[DbSizeDailySample]
    usage: CollectionResult[UsageSample]
    schema_version: str = SCHEMA_VERSION
    collection_time: datetime = field(default_factory=_utc_now)
    # The Exasol server's own clock at collection time (naive, server civil
    # time -- see probe_database_time). Rules computing an age/duration
    # against a DB-sourced timestamp (e.g. session age from LOGIN_TIME) must
    # use this, not collection_time, to avoid a naive/aware datetime clash
    # and to avoid clock-skew/timezone mismatch with the machine running
    # ExaDoctor. None only if the CURRENT_TIMESTAMP probe itself failed.
    database_time: datetime | None = None
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "database": self.database.to_dict(),
            "collection_time": self.collection_time.isoformat(),
            "database_time": self.database_time.isoformat() if self.database_time else None,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "metadata": self.metadata.to_dict(),
            "parameters": self.parameters.to_dict(),
            "sessions": self.sessions.to_dict(),
            "workload": self.workload.to_dict(),
            "monitoring": self.monitoring.to_dict(),
            "storage": self.storage.to_dict(),
            "usage": self.usage.to_dict(),
            "findings": [f.to_dict() for f in self.findings],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        return cls(
            schema_version=data["schema_version"],
            database=DatabaseInfo.from_dict(data["database"]),
            collection_time=datetime.fromisoformat(data["collection_time"]),
            database_time=(datetime.fromisoformat(data["database_time"]) if data.get("database_time") else None),
            capabilities=[Capability.from_dict(c) for c in data["capabilities"]],
            metadata=CollectionResult.from_dict(data["metadata"], MetadataProperty),
            parameters=CollectionResult.from_dict(data["parameters"], Parameter),
            sessions=CollectionResult.from_dict(data["sessions"], SessionInfo),
            workload=CollectionResult.from_dict(data["workload"], SqlStatement),
            monitoring=CollectionResult.from_dict(data["monitoring"], MonitorSample),
            storage=CollectionResult.from_dict(data["storage"], DbSizeDailySample),
            usage=CollectionResult.from_dict(data["usage"], UsageSample),
            findings=[Finding.from_dict(f) for f in data["findings"]],
        )


def build_snapshot(gateway: SqlGateway, host: str, port: int) -> Snapshot:
    """Probe capabilities and run every collector to build a fresh Snapshot.

    Note: this issues its own EXA_METADATA lookup (via probe_all) separate
    from collect_all's own metadata collector -- a small amount of
    redundant querying traded for keeping capability probing and data
    collection as independent, separately testable concerns.
    """
    database_version, capabilities = probe_all(gateway, PUBLIC_SOURCES)
    database_time = probe_database_time(gateway)
    collected = collect_all(gateway)

    return Snapshot(
        database=DatabaseInfo(host=host, port=port, version=database_version),
        database_time=database_time,
        capabilities=capabilities,
        metadata=collected["metadata"],
        parameters=collected["parameters"],
        sessions=collected["sessions"],
        workload=collected["workload"],
        monitoring=collected["monitoring"],
        storage=collected["storage"],
        usage=collected["usage"],
    )
