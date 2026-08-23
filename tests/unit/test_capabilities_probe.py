"""Unit tests for capability probing, against a fake fixture gateway.

The fake gateway only understands the exact SQL shapes probe.py is known to
issue (asserted, not guessed) -- see the shapes documented in
exadoctor.capabilities.probe's module docstring. Anything else raises
AssertionError so an accidental change in probe.py's SQL shape fails loudly
here instead of silently testing the wrong thing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytest

from exadoctor.capabilities.probe import probe_all, probe_database_version, probe_source
from exadoctor.capabilities.sources import SourceSpec
from exadoctor.connection.gateway import QueryResult
from exadoctor.errors import ConnectionFailedError


@dataclass
class FakeTable:
    columns: set[str]
    row_count: int


class FakeGateway:
    def __init__(self, tables: dict[tuple[str, str], FakeTable], param_values: dict[str, str] | None = None):
        self.tables = tables
        self.param_values = param_values or {}
        self.queries: list[str] = []
        self.raise_for_table: tuple[str, str] | None = None

    def execute(self, sql: str) -> QueryResult:
        self.queries.append(sql)

        version_match = re.search(r"PARAM_NAME\"\s*=\s*'([^']+)'", sql)
        if "EXA_METADATA" in sql and version_match:
            key = version_match.group(1)
            if key not in self.param_values:
                raise ConnectionFailedError(f"object {key} not found")
            return QueryResult(columns=["PARAM_VALUE"], rows=[(self.param_values[key],)])

        bulk_match = re.search(r'FROM \(SELECT (.+) FROM "([^"]+)"\."([^"]+)"\) AS PROBE', sql)
        if bulk_match:
            cols_raw, schema, table = bulk_match.groups()
            self._maybe_raise_injected(schema, table)
            cols = [c.strip().strip('"') for c in cols_raw.split(",")]
            table_def = self._require_table(schema, table)
            missing = [c for c in cols if c not in table_def.columns]
            if missing:
                raise ConnectionFailedError(f"object {missing[0]} not found")
            return QueryResult(columns=["ROW_COUNT"], rows=[(table_def.row_count,)])

        single_col_match = re.search(r'SELECT "([^"]+)" FROM "([^"]+)"\."([^"]+)" LIMIT 1', sql)
        if single_col_match:
            col, schema, table = single_col_match.groups()
            table_def = self._require_table(schema, table)
            if col not in table_def.columns:
                raise ConnectionFailedError(f"object {col} not found")
            return QueryResult(columns=[col], rows=[(None,)])

        count_match = re.match(r'SELECT COUNT\(\*\) AS ROW_COUNT FROM "([^"]+)"\."([^"]+)"$', sql.strip())
        if count_match:
            schema, table = count_match.groups()
            self._maybe_raise_injected(schema, table)
            table_def = self._require_table(schema, table)
            return QueryResult(columns=["ROW_COUNT"], rows=[(table_def.row_count,)])

        raise AssertionError(f"FakeGateway does not know how to handle: {sql!r}")

    def _require_table(self, schema: str, table: str) -> FakeTable:
        table_def = self.tables.get((schema, table))
        if table_def is None:
            raise ConnectionFailedError(f"object {schema}.{table} not found")
        return table_def

    def _maybe_raise_injected(self, schema: str, table: str) -> None:
        if self.raise_for_table == (schema, table):
            raise RuntimeError("simulated unexpected driver failure")


FULL_SOURCE = SourceSpec(
    id="FULL_SOURCE",
    schema="EXA_STATISTICS",
    table="FULL_SOURCE",
    required_columns=("A", "B"),
)

MISSING_TABLE_SOURCE = SourceSpec(
    id="MISSING_TABLE_SOURCE",
    schema="EXA_STATISTICS",
    table="DOES_NOT_EXIST",
    required_columns=("A", "B"),
)

PARTIAL_SOURCE = SourceSpec(
    id="PARTIAL_SOURCE",
    schema="EXA_STATISTICS",
    table="PARTIAL_SOURCE",
    required_columns=("A", "B", "C"),
)


def test_probe_source_fully_available_with_data() -> None:
    gateway = FakeGateway({("EXA_STATISTICS", "FULL_SOURCE"): FakeTable(columns={"A", "B"}, row_count=5)})

    capability = probe_source(gateway, FULL_SOURCE, database_version="2026.1.0")

    assert capability.available is True
    assert capability.reason is None
    assert capability.detected_columns == ["A", "B"]
    assert capability.missing_columns == []
    assert capability.data_available is True
    assert capability.database_version == "2026.1.0"


def test_probe_source_available_but_empty() -> None:
    gateway = FakeGateway({("EXA_STATISTICS", "FULL_SOURCE"): FakeTable(columns={"A", "B"}, row_count=0)})

    capability = probe_source(gateway, FULL_SOURCE, database_version=None)

    assert capability.available is True
    assert capability.data_available is False


def test_probe_source_missing_table_reports_unavailable_with_reason() -> None:
    gateway = FakeGateway({})

    capability = probe_source(gateway, MISSING_TABLE_SOURCE, database_version=None)

    assert capability.available is False
    assert capability.reason is not None
    assert "not found" in capability.reason
    assert capability.detected_columns == []
    assert capability.missing_columns == ["A", "B"]
    assert capability.data_available is None


def test_probe_source_falls_back_to_per_column_check_on_partial_schema() -> None:
    gateway = FakeGateway(
        {("EXA_STATISTICS", "PARTIAL_SOURCE"): FakeTable(columns={"A", "B"}, row_count=3)}
    )

    capability = probe_source(gateway, PARTIAL_SOURCE, database_version=None)

    assert capability.available is False
    assert capability.detected_columns == ["A", "B"]
    assert capability.missing_columns == ["C"]
    assert "C" in (capability.reason or "")


def test_probe_database_version_reads_metadata() -> None:
    gateway = FakeGateway({}, param_values={"databaseProductVersion": "2026.1.0"})
    assert probe_database_version(gateway) == "2026.1.0"


def test_probe_database_version_returns_none_when_unavailable() -> None:
    gateway = FakeGateway({})
    assert probe_database_version(gateway) is None


def test_probe_all_is_independent_per_source() -> None:
    gateway = FakeGateway(
        {
            ("EXA_STATISTICS", "FULL_SOURCE"): FakeTable(columns={"A", "B"}, row_count=1),
        },
        param_values={"databaseProductVersion": "2026.1.0"},
    )

    version, capabilities = probe_all(gateway, (FULL_SOURCE, MISSING_TABLE_SOURCE))

    assert version == "2026.1.0"
    by_id = {c.id: c for c in capabilities}
    assert by_id["FULL_SOURCE"].available is True
    assert by_id["MISSING_TABLE_SOURCE"].available is False


def test_probe_all_survives_unexpected_exception_in_one_source() -> None:
    gateway = FakeGateway(
        {
            ("EXA_STATISTICS", "FULL_SOURCE"): FakeTable(columns={"A", "B"}, row_count=1),
        }
    )
    gateway.raise_for_table = ("EXA_STATISTICS", "FULL_SOURCE")

    version, capabilities = probe_all(gateway, (FULL_SOURCE, MISSING_TABLE_SOURCE))

    assert len(capabilities) == 2
    by_id = {c.id: c for c in capabilities}
    assert by_id["FULL_SOURCE"].available is False
    assert "simulated unexpected driver failure" in (by_id["FULL_SOURCE"].reason or "")
    assert by_id["MISSING_TABLE_SOURCE"].available is False


def test_fake_gateway_rejects_unknown_query_shapes() -> None:
    gateway = FakeGateway({})
    with pytest.raises(AssertionError):
        gateway.execute("DROP TABLE x")
