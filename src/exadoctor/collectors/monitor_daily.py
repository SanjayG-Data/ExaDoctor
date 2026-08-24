"""Collector for EXA_MONITOR_DAILY (daily-aggregated system resource trend).

Like EXA_DB_SIZE_DAILY, this accumulates indefinitely rather than rolling
off after 24 hours -- confirmed live it holds a cluster's whole lifetime
of daily rollups (e.g. 53 rows spanning ~3 months on the test instance) --
so it needs the same explicit window to avoid an unbounded scan.

Only a curated subset of EXA_MONITOR_DAILY's ~40 columns is selected: the
four metrics SYS-RESOURCE-TREND-001 actually checks (CPU, TEMP_DB_RAM,
NET, SWAP averages). The table also carries HDD/LOCAL/CACHE/REMOTE
read/write size and duration averages, which are more query-profile-level
concerns already covered elsewhere (or not yet needed) -- narrowing the
SELECT list, same discipline as every other collector here.
"""

from __future__ import annotations

from exadoctor.collectors.base import run_bounded_collector
from exadoctor.collectors.models import CollectionResult, MonitorDailySample
from exadoctor.connection.gateway import SqlGateway

DEFAULT_WINDOW_DAYS = 90


def _row_factory(row: tuple) -> MonitorDailySample:
    (
        cluster_name,
        interval_start,
        cpu_avg,
        temp_db_ram_avg,
        net_avg,
        swap_avg,
    ) = row
    return MonitorDailySample(
        cluster_name=cluster_name,
        interval_start=interval_start,
        cpu_avg_percent=float(cpu_avg) if cpu_avg is not None else None,
        temp_db_ram_avg_mib=float(temp_db_ram_avg) if temp_db_ram_avg is not None else None,
        net_avg_mib_per_sec=float(net_avg) if net_avg is not None else None,
        swap_avg_mib_per_sec=float(swap_avg) if swap_avg is not None else None,
    )


def collect_monitor_daily(
    gateway: SqlGateway, window_days: int = DEFAULT_WINDOW_DAYS
) -> CollectionResult[MonitorDailySample]:
    if window_days <= 0:
        raise ValueError("window_days must be positive")

    # window_days is coerced to int before interpolation, so this cannot
    # carry SQL metacharacters regardless of caller input.
    sql = (
        'SELECT "CLUSTER_NAME", "INTERVAL_START", "CPU_AVG", "TEMP_DB_RAM_AVG", "NET_AVG", "SWAP_AVG" '
        'FROM "EXA_STATISTICS"."EXA_MONITOR_DAILY" '
        f"WHERE \"INTERVAL_START\" >= CURRENT_DATE - INTERVAL '{int(window_days)}' DAY"
    )
    return run_bounded_collector(gateway, source_id="EXA_MONITOR_DAILY", sql=sql, row_factory=_row_factory)
