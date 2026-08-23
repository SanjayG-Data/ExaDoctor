"""Collector for EXA_PARAMETERS (system/session database parameters)."""

from __future__ import annotations

from exadoctor.collectors.base import run_bounded_collector
from exadoctor.collectors.models import CollectionResult, Parameter
from exadoctor.connection.gateway import SqlGateway

SQL = (
    'SELECT "PARAMETER_NAME", "SESSION_VALUE", "SYSTEM_VALUE" '
    'FROM "SYS"."EXA_PARAMETERS"'
)


def _row_factory(row: tuple) -> Parameter:
    parameter_name, session_value, system_value = row
    return Parameter(parameter_name=parameter_name, session_value=session_value, system_value=system_value)


def collect_parameters(gateway: SqlGateway) -> CollectionResult[Parameter]:
    return run_bounded_collector(gateway, source_id="EXA_PARAMETERS", sql=SQL, row_factory=_row_factory)
