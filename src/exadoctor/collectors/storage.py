"""Collector for EXA_DB_SIZE_DAILY (daily aggregated capacity/growth trend).

Unlike the other public sources, EXA_DB_SIZE_DAILY accumulates indefinitely
rather than rolling off after 24 hours, so it needs an explicit window to
avoid an unbounded scan (roadmap section 11.4).
"""

from __future__ import annotations

from exadoctor.collectors.base import run_bounded_collector
from exadoctor.collectors.models import CollectionResult, DbSizeDailySample
from exadoctor.connection.gateway import SqlGateway

DEFAULT_WINDOW_DAYS = 90


def _row_factory(row: tuple) -> DbSizeDailySample:
    (
        cluster_name,
        interval_start,
        storage_size_avg,
        storage_size_max,
        use_avg,
        use_max,
        recommended_db_ram_size_avg,
        object_count_avg,
    ) = row
    return DbSizeDailySample(
        cluster_name=cluster_name,
        interval_start=interval_start,
        storage_size_avg_gib=float(storage_size_avg) if storage_size_avg is not None else None,
        storage_size_max_gib=float(storage_size_max) if storage_size_max is not None else None,
        use_avg_percent=float(use_avg) if use_avg is not None else None,
        use_max_percent=float(use_max) if use_max is not None else None,
        recommended_db_ram_size_avg_gib=(
            float(recommended_db_ram_size_avg) if recommended_db_ram_size_avg is not None else None
        ),
        object_count_avg=float(object_count_avg) if object_count_avg is not None else None,
    )


def collect_db_size_daily(
    gateway: SqlGateway, window_days: int = DEFAULT_WINDOW_DAYS
) -> CollectionResult[DbSizeDailySample]:
    if window_days <= 0:
        raise ValueError("window_days must be positive")

    # window_days is coerced to int before interpolation, so this cannot
    # carry SQL metacharacters regardless of caller input.
    sql = (
        'SELECT "CLUSTER_NAME", "INTERVAL_START", "STORAGE_SIZE_AVG", "STORAGE_SIZE_MAX", '
        '"USE_AVG", "USE_MAX", "RECOMMENDED_DB_RAM_SIZE_AVG", "OBJECT_COUNT_AVG" '
        'FROM "EXA_STATISTICS"."EXA_DB_SIZE_DAILY" '
        f"WHERE \"INTERVAL_START\" >= CURRENT_DATE - INTERVAL '{int(window_days)}' DAY"
    )
    return run_bounded_collector(gateway, source_id="EXA_DB_SIZE_DAILY", sql=sql, row_factory=_row_factory)
