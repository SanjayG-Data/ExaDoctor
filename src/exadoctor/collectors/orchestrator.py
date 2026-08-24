"""Runs every public collector independently.

Each `collect_*` function already catches all failures internally (see
`run_bounded_collector`), so a single broken source can never prevent this
function from returning results for the rest.
"""

from __future__ import annotations

from typing import Any

from exadoctor.collectors.metadata import collect_metadata
from exadoctor.collectors.models import CollectionResult
from exadoctor.collectors.monitor_daily import collect_monitor_daily
from exadoctor.collectors.monitoring import collect_monitor_last_day
from exadoctor.collectors.parameters import collect_parameters
from exadoctor.collectors.session_history import collect_session_history
from exadoctor.collectors.sessions import collect_sessions
from exadoctor.collectors.sql_daily import collect_sql_daily
from exadoctor.collectors.storage import collect_db_size_daily
from exadoctor.collectors.system_events import collect_system_events
from exadoctor.collectors.transaction_conflicts import collect_transaction_conflicts
from exadoctor.collectors.usage import collect_usage_last_day
from exadoctor.collectors.workload import collect_sql_last_day
from exadoctor.connection.gateway import SqlGateway


def collect_all(gateway: SqlGateway) -> dict[str, CollectionResult[Any]]:
    return {
        "metadata": collect_metadata(gateway),
        "parameters": collect_parameters(gateway),
        "sessions": collect_sessions(gateway),
        "session_history": collect_session_history(gateway),
        "workload": collect_sql_last_day(gateway),
        "sql_daily": collect_sql_daily(gateway),
        "monitoring": collect_monitor_last_day(gateway),
        "monitor_daily": collect_monitor_daily(gateway),
        "storage": collect_db_size_daily(gateway),
        "usage": collect_usage_last_day(gateway),
        "system_events": collect_system_events(gateway),
        "transaction_conflicts": collect_transaction_conflicts(gateway),
    }
