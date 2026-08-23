"""Collector for EXA_METADATA (database properties)."""

from __future__ import annotations

from exadoctor.collectors.base import run_bounded_collector
from exadoctor.collectors.models import CollectionResult, MetadataProperty
from exadoctor.connection.gateway import SqlGateway

SQL = 'SELECT "PARAM_NAME", "PARAM_VALUE" FROM "SYS"."EXA_METADATA"'


def _row_factory(row: tuple) -> MetadataProperty:
    param_name, param_value = row
    return MetadataProperty(param_name=param_name, param_value=param_value)


def collect_metadata(gateway: SqlGateway) -> CollectionResult[MetadataProperty]:
    return run_bounded_collector(gateway, source_id="EXA_METADATA", sql=SQL, row_factory=_row_factory)
