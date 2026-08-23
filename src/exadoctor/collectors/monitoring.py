"""Collector for EXA_MONITOR_LAST_DAY (cluster monitoring metrics, last 24 hours)."""

from __future__ import annotations

from exadoctor.collectors.base import run_bounded_collector
from exadoctor.collectors.models import CollectionResult, MonitorSample
from exadoctor.connection.gateway import SqlGateway

SQL = (
    'SELECT "CLUSTER_NAME", "MEASURE_TIME", "LOAD", "CPU", "TEMP_DB_RAM", '
    '"PERSISTENT_DB_RAM", "NET", "SWAP" FROM "EXA_STATISTICS"."EXA_MONITOR_LAST_DAY"'
)


def _row_factory(row: tuple) -> MonitorSample:
    cluster_name, measure_time, load, cpu, temp_db_ram, persistent_db_ram, net, swap = row
    return MonitorSample(
        cluster_name=cluster_name,
        measure_time=measure_time,
        load=float(load) if load is not None else None,
        cpu_percent=float(cpu) if cpu is not None else None,
        temp_db_ram_mib=float(temp_db_ram) if temp_db_ram is not None else None,
        persistent_db_ram_mib=float(persistent_db_ram) if persistent_db_ram is not None else None,
        net_mib_per_sec=float(net) if net is not None else None,
        swap_mib_per_sec=float(swap) if swap is not None else None,
    )


def collect_monitor_last_day(gateway: SqlGateway) -> CollectionResult[MonitorSample]:
    return run_bounded_collector(gateway, source_id="EXA_MONITOR_LAST_DAY", sql=SQL, row_factory=_row_factory)
