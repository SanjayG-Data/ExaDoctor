"""Collector for EXA_USAGE_LAST_DAY (DBMS usage, last 24 hours)."""

from __future__ import annotations

from exadoctor.collectors.base import run_bounded_collector
from exadoctor.collectors.models import CollectionResult, UsageSample
from exadoctor.connection.gateway import SqlGateway

SQL = 'SELECT "CLUSTER_NAME", "MEASURE_TIME", "USERS", "QUERIES" FROM "EXA_STATISTICS"."EXA_USAGE_LAST_DAY"'


def _row_factory(row: tuple) -> UsageSample:
    cluster_name, measure_time, users, queries = row
    return UsageSample(cluster_name=cluster_name, measure_time=measure_time, users=users, queries=queries)


def collect_usage_last_day(gateway: SqlGateway) -> CollectionResult[UsageSample]:
    return run_bounded_collector(gateway, source_id="EXA_USAGE_LAST_DAY", sql=SQL, row_factory=_row_factory)
