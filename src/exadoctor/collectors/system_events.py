"""Collector for EXA_SYSTEM_EVENTS (startup/shutdown/restart event log,
including the DB RAM/node/vCPU sizing in effect at each event).

Unlike EXA_DB_SIZE_DAILY, this table is not a rolling telemetry stream --
it only gains a row per lifecycle event (startup, restart, backup, ...), so
it stays small over a cluster's realistic lifetime and needs no window.
"""

from __future__ import annotations

from exadoctor.collectors.base import run_bounded_collector
from exadoctor.collectors.models import CollectionResult, SystemEvent
from exadoctor.connection.gateway import SqlGateway

SQL = (
    'SELECT "CLUSTER_NAME", "MEASURE_TIME", "EVENT_TYPE", "DBMS_VERSION", '
    '"NODES", "DB_RAM_SIZE", "VCPU" FROM "EXA_STATISTICS"."EXA_SYSTEM_EVENTS"'
)


def _row_factory(row: tuple) -> SystemEvent:
    (
        cluster_name,
        measure_time,
        event_type,
        dbms_version,
        nodes,
        db_ram_size,
        vcpu,
    ) = row
    return SystemEvent(
        cluster_name=cluster_name,
        measure_time=measure_time,
        event_type=event_type,
        dbms_version=dbms_version,
        nodes=int(nodes) if nodes is not None else None,
        db_ram_size_gib=float(db_ram_size) if db_ram_size is not None else None,
        vcpu=int(vcpu) if vcpu is not None else None,
    )


def collect_system_events(gateway: SqlGateway) -> CollectionResult[SystemEvent]:
    return run_bounded_collector(gateway, source_id="EXA_SYSTEM_EVENTS", sql=SQL, row_factory=_row_factory)
