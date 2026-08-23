from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from exadoctor.baseline.compare import MIN_SAMPLES_FOR_COMPARISON, compare_snapshots, render_comparison_text
from exadoctor.collectors.models import CollectionResult, DbSizeDailySample, SqlStatement
from exadoctor.models.snapshot import Snapshot

FIXTURE_PATH = Path(__file__).parent.parent / "golden" / "sample_snapshot.json"


def _base_snapshot() -> Snapshot:
    return Snapshot.from_dict(json.loads(FIXTURE_PATH.read_text()))


def _sql_statement(command_class: str, duration_seconds: float, temp_mib: float = 0.0) -> SqlStatement:
    return SqlStatement(
        session_id=1,
        stmt_id=1,
        command_name=command_class,
        command_class=command_class,
        duration_seconds=duration_seconds,
        start_time=datetime(2026, 8, 20, tzinfo=timezone.utc),
        stop_time=datetime(2026, 8, 20, tzinfo=timezone.utc),
        cpu_percent=1.0,
        temp_db_ram_peak_mib=temp_mib,
        local_read_size_mib=0.0,
        remote_read_size_mib=0.0,
        net_mib_per_sec=0.0,
        success=True,
        error_code=None,
        error_text=None,
        row_count=0,
        cluster_name="MAIN",
    )


def _workload_result(statements: list[SqlStatement]) -> CollectionResult[SqlStatement]:
    return CollectionResult(source_id="EXA_SQL_LAST_DAY", stability="PUBLIC", available=True, reason=None, rows=statements)


def _unavailable_workload_result(reason: str = "denied") -> CollectionResult[SqlStatement]:
    return CollectionResult(source_id="EXA_SQL_LAST_DAY", stability="PUBLIC", available=False, reason=reason, rows=[])


def _storage_sample(day_offset: int, avg_gib: float) -> DbSizeDailySample:
    return DbSizeDailySample(
        cluster_name="MAIN",
        interval_start=datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(days=day_offset),
        storage_size_avg_gib=avg_gib,
        storage_size_max_gib=avg_gib,
        use_avg_percent=50.0,
        use_max_percent=60.0,
        recommended_db_ram_size_avg_gib=10.0,
        object_count_avg=100.0,
    )


def _storage_result(samples: list[DbSizeDailySample]) -> CollectionResult[DbSizeDailySample]:
    return CollectionResult(source_id="EXA_DB_SIZE_DAILY", stability="PUBLIC", available=True, reason=None, rows=samples)


def test_duration_increase_detected() -> None:
    baseline = _base_snapshot()
    current = _base_snapshot()

    baseline.workload = _workload_result([_sql_statement("SELECT", d) for d in [1.0, 1.1, 0.9, 1.0, 1.05]])
    current.workload = _workload_result([_sql_statement("SELECT", d) for d in [2.0, 2.1, 1.9, 2.0, 2.05]])

    result = compare_snapshots(baseline, current)

    select_change = next(m for m in result.duration_by_class if "SELECT" in m.metric)
    assert select_change.comparable is True
    assert select_change.baseline_value == pytest.approx(1.0, abs=0.01)
    assert select_change.current_value == pytest.approx(2.0, abs=0.01)
    assert select_change.absolute_change is not None and select_change.absolute_change > 0
    assert select_change.relative_change_percent == pytest.approx(100.0, abs=5)


def test_storage_growth_detected() -> None:
    baseline = _base_snapshot()
    current = _base_snapshot()

    baseline.storage = _storage_result([_storage_sample(i, 100.0) for i in range(5)])
    current.storage = _storage_result([_storage_sample(i, 100.0) for i in range(4)] + [_storage_sample(4, 250.0)])

    result = compare_snapshots(baseline, current)

    assert result.storage.comparable is True
    assert result.storage.baseline_value == pytest.approx(100.0)
    assert result.storage.current_value == pytest.approx(250.0)
    assert result.storage.absolute_change == pytest.approx(150.0)
    assert result.storage.relative_change_percent == pytest.approx(150.0)


def test_unavailable_workload_reported_as_not_comparable_not_as_no_change() -> None:
    baseline = _base_snapshot()
    current = _base_snapshot()

    baseline.workload = _unavailable_workload_result("EXA_SQL_LAST_DAY: insufficient privileges")
    current.workload = _workload_result([_sql_statement("SELECT", d) for d in [1.0, 1.1, 0.9, 1.0, 1.05]])

    result = compare_snapshots(baseline, current)

    assert result.temp_usage.comparable is False
    assert result.temp_usage.absolute_change is None
    assert result.temp_usage.reason

    assert len(result.duration_by_class) == 1
    assert result.duration_by_class[0].comparable is False
    # Must not silently report "no change" (a zero absolute_change) when data is missing.
    assert result.duration_by_class[0].absolute_change is None


def test_too_few_samples_reported_as_not_comparable() -> None:
    baseline = _base_snapshot()
    current = _base_snapshot()

    baseline.workload = _workload_result([_sql_statement("SELECT", 1.0)])
    current.workload = _workload_result([_sql_statement("SELECT", 2.0)])

    result = compare_snapshots(baseline, current)

    select_change = next(m for m in result.duration_by_class if "SELECT" in m.metric)
    assert select_change.comparable is False
    assert select_change.absolute_change is None
    assert select_change.reason is not None and str(MIN_SAMPLES_FOR_COMPARISON) in select_change.reason


def test_render_comparison_text_handles_unavailable_data_without_crashing() -> None:
    baseline = _base_snapshot()
    current = _base_snapshot()
    baseline.workload = _unavailable_workload_result()
    current.workload = _unavailable_workload_result()
    baseline.storage = CollectionResult(source_id="EXA_DB_SIZE_DAILY", stability="PUBLIC", available=False, reason="denied", rows=[])
    current.storage = CollectionResult(source_id="EXA_DB_SIZE_DAILY", stability="PUBLIC", available=False, reason="denied", rows=[])

    result = compare_snapshots(baseline, current)
    text = render_comparison_text(result)

    assert "NOT COMPARABLE" in text
    assert "EXADOCTOR BASELINE COMPARISON" in text
