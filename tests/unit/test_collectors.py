"""Unit tests for public collectors, against a scripted fake gateway.

Each collector issues one fixed, known SQL statement (exposed as a module-
level `SQL` constant), so the fake matches on exact SQL text rather than
pattern-guessing -- if a collector's query shape changes, the test breaks
loudly instead of silently testing something else.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from exadoctor.collectors import (
    metadata,
    monitoring,
    parameters,
    sessions,
    storage,
    system_events,
    transaction_conflicts,
    usage,
    workload,
)
from exadoctor.collectors.base import run_bounded_collector
from exadoctor.collectors.orchestrator import collect_all
from exadoctor.connection.gateway import QueryResult
from exadoctor.errors import ConnectionFailedError


class ScriptedGateway:
    def __init__(self, responses: dict[str, QueryResult | Exception]):
        self.responses = responses
        self.queries: list[str] = []

    def execute(self, sql: str) -> QueryResult:
        self.queries.append(sql)
        response = self.responses.get(sql)
        if response is None:
            raise AssertionError(f"ScriptedGateway has no response for: {sql!r}")
        if isinstance(response, Exception):
            raise response
        return response


def test_collect_metadata_maps_rows() -> None:
    gateway = ScriptedGateway(
        {metadata.SQL: QueryResult(columns=["PARAM_NAME", "PARAM_VALUE"], rows=[("databaseProductVersion", "2026.1.0")])}
    )
    result = metadata.collect_metadata(gateway)
    assert result.available is True
    assert result.rows[0].param_name == "databaseProductVersion"
    assert result.rows[0].param_value == "2026.1.0"


def test_collect_parameters_handles_null_values() -> None:
    gateway = ScriptedGateway(
        {parameters.SQL: QueryResult(columns=[], rows=[("SOME_PARAM", None, "5")])}
    )
    result = parameters.collect_parameters(gateway)
    assert result.rows[0].session_value is None
    assert result.rows[0].system_value == "5"


@pytest.mark.parametrize(
    "raw_duration,expected_seconds",
    [
        ("0:00:41", 41.0),
        ("1:13:36", 1 * 3600 + 13 * 60 + 36),
        ("0:33:17", 33 * 60 + 17),
        (None, None),
        ("garbage", None),
        ("1:2", None),
    ],
)
def test_collect_sessions_parses_hms_duration(raw_duration: str | None, expected_seconds: float | None) -> None:
    gateway = ScriptedGateway(
        {
            sessions.SQL: QueryResult(
                columns=[],
                rows=[(4, "SYS", "IDLE", None, None, raw_duration, datetime(2026, 8, 22, 11, 48, 15), Decimal("66.9"), None, None, None)],
            )
        }
    )
    result = sessions.collect_sessions(gateway)
    assert result.available is True
    assert result.rows[0].duration_seconds == expected_seconds
    assert result.rows[0].temp_db_ram_mib == 66.9


def test_collect_sql_last_day_converts_types() -> None:
    gateway = ScriptedGateway(
        {
            workload.SQL: QueryResult(
                columns=[],
                rows=[
                    (
                        1874035687682015232,
                        133,
                        "SELECT",
                        "DQL",
                        Decimal("0.002"),
                        datetime(2026, 8, 21, 13, 43, 52),
                        datetime(2026, 8, 21, 13, 43, 52),
                        Decimal("4.5"),
                        None,
                        None,
                        None,
                        None,
                        True,
                        None,
                        None,
                        0,
                        "cluster1",
                    )
                ],
            )
        }
    )
    result = workload.collect_sql_last_day(gateway)
    row = result.rows[0]
    assert row.session_id == 1874035687682015232
    assert row.duration_seconds == 0.002
    assert row.cpu_percent == 4.5
    assert row.success is True
    assert row.row_count == 0


def test_collect_monitor_last_day_maps_rows() -> None:
    gateway = ScriptedGateway(
        {
            monitoring.SQL: QueryResult(
                columns=[],
                rows=[("cluster1", datetime(2026, 8, 22, 13, 0), Decimal("0.2"), Decimal("4.5"), None, None, None, Decimal("0"))],
            )
        }
    )
    result = monitoring.collect_monitor_last_day(gateway)
    assert result.rows[0].swap_mib_per_sec == 0.0


def test_collect_usage_last_day_maps_rows() -> None:
    gateway = ScriptedGateway(
        {usage.SQL: QueryResult(columns=[], rows=[("cluster1", datetime(2026, 8, 22, 13, 0), 3, 1)])}
    )
    result = usage.collect_usage_last_day(gateway)
    assert result.rows[0].users == 3
    assert result.rows[0].queries == 1


def test_collect_db_size_daily_uses_default_window_in_sql() -> None:
    captured_sql = {}

    class CapturingGateway:
        def execute(self, sql: str) -> QueryResult:
            captured_sql["sql"] = sql
            return QueryResult(columns=[], rows=[])

    storage.collect_db_size_daily(CapturingGateway())
    assert "INTERVAL '90' DAY" in captured_sql["sql"]


def test_collect_db_size_daily_rejects_non_positive_window() -> None:
    with pytest.raises(ValueError):
        storage.collect_db_size_daily(ScriptedGateway({}), window_days=0)


def test_collect_system_events_maps_rows() -> None:
    gateway = ScriptedGateway(
        {
            system_events.SQL: QueryResult(
                columns=[],
                rows=[("MAIN", datetime(2026, 8, 22, 11, 48, 15, 908000), "STARTUP", "2026.1.0", 1, Decimal("2"), 22)],
            )
        }
    )
    result = system_events.collect_system_events(gateway)
    assert result.rows[0].event_type == "STARTUP"
    assert result.rows[0].db_ram_size_gib == 2.0
    assert result.rows[0].nodes == 1
    assert result.rows[0].vcpu == 22


def test_collect_transaction_conflicts_uses_default_window_in_sql() -> None:
    captured_sql = {}

    class CapturingGateway:
        def execute(self, sql: str) -> QueryResult:
            captured_sql["sql"] = sql
            return QueryResult(columns=[], rows=[])

    transaction_conflicts.collect_transaction_conflicts(CapturingGateway())
    assert "INTERVAL '1' DAY" in captured_sql["sql"]


def test_collect_transaction_conflicts_rejects_non_positive_window() -> None:
    with pytest.raises(ValueError):
        transaction_conflicts.collect_transaction_conflicts(ScriptedGateway({}), window_days=0)


def test_collect_transaction_conflicts_maps_rows_including_open_conflict() -> None:
    class CapturingGateway:
        def execute(self, sql: str) -> QueryResult:
            return QueryResult(
                columns=[],
                rows=[
                    (
                        1870936279216291840,
                        1870936279003561984,
                        datetime(2026, 8, 22, 11, 32, 1, 246000),
                        datetime(2026, 8, 22, 11, 32, 1, 280000),
                        "WAIT FOR COMMIT",
                        "MARKET.SIGNALS",
                        None,
                    ),
                    # STOP_TIME NULL -- conflict still open at collection time.
                    (
                        1870936279356473344,
                        1870936279216291840,
                        datetime(2026, 8, 22, 11, 33, 0, 0),
                        None,
                        "WAIT FOR COMMIT",
                        "MARKET.SIGNALS",
                        None,
                    ),
                ],
            )

    result = transaction_conflicts.collect_transaction_conflicts(CapturingGateway())
    assert len(result.rows) == 2
    assert result.rows[0].stop_time is not None
    assert result.rows[1].stop_time is None


def test_collector_degrades_gracefully_on_query_failure() -> None:
    gateway = ScriptedGateway({metadata.SQL: ConnectionFailedError("object EXA_METADATA not found")})
    result = metadata.collect_metadata(gateway)
    assert result.available is False
    assert "not found" in (result.reason or "")
    assert result.rows == []


def test_run_bounded_collector_skips_malformed_rows_without_dropping_the_rest() -> None:
    gateway = ScriptedGateway({"SELECT 1": QueryResult(columns=[], rows=[(1,), ("bad",), (3,)])})

    def row_factory(row: tuple) -> int:
        return int(row[0])  # "bad" -> ValueError, must be skipped not fatal

    result = run_bounded_collector(gateway, source_id="TEST", sql="SELECT 1", row_factory=row_factory)

    assert result.available is True
    assert result.rows == [1, 3]
    assert "1 row(s) skipped" in (result.reason or "")


def test_collect_all_survives_one_failing_collector() -> None:
    gateway = ScriptedGateway(
        {
            metadata.SQL: ConnectionFailedError("boom"),
            parameters.SQL: QueryResult(columns=[], rows=[]),
            sessions.SQL: QueryResult(columns=[], rows=[]),
            workload.SQL: QueryResult(columns=[], rows=[]),
            monitoring.SQL: QueryResult(columns=[], rows=[]),
            usage.SQL: QueryResult(columns=[], rows=[]),
            system_events.SQL: QueryResult(columns=[], rows=[]),
        }
    )
    # storage.py and transaction_conflicts.py both build their SQL
    # dynamically (window clause), so match on a substring for those instead
    # of an exact-string key.
    class GatewayWithStorage(ScriptedGateway):
        def execute(self, sql: str) -> QueryResult:
            if "EXA_DB_SIZE_DAILY" in sql or "EXA_DBA_TRANSACTION_CONFLICTS" in sql:
                return QueryResult(columns=[], rows=[])
            return super().execute(sql)

    gateway2 = GatewayWithStorage(gateway.responses)
    results = collect_all(gateway2)

    assert set(results.keys()) == {
        "metadata",
        "parameters",
        "sessions",
        "workload",
        "monitoring",
        "storage",
        "usage",
        "system_events",
        "transaction_conflicts",
    }
    assert results["metadata"].available is False
    assert results["parameters"].available is True
