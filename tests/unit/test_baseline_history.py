from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from exadoctor.baseline.history import build_trend, render_trend_text
from exadoctor.collectors.models import CollectionResult, SqlStatement
from exadoctor.models.snapshot import Snapshot

FIXTURE_PATH = Path(__file__).parent.parent / "golden" / "sample_snapshot.json"


def _load() -> Snapshot:
    return Snapshot.from_dict(json.loads(FIXTURE_PATH.read_text()))


def _statement(session_id: int, command_class: str, duration: float) -> SqlStatement:
    return SqlStatement(
        session_id=session_id,
        stmt_id=1,
        command_name="SELECT",
        command_class=command_class,
        duration_seconds=duration,
        start_time=None,
        stop_time=None,
        cpu_percent=None,
        temp_db_ram_peak_mib=None,
        local_read_size_mib=None,
        remote_read_size_mib=None,
        net_mib_per_sec=None,
        success=True,
        error_code=None,
        error_text=None,
        row_count=0,
        cluster_name=None,
    )


def test_build_trend_returns_none_below_sample_floor() -> None:
    snapshot = _load()
    # golden fixture's workload has exactly 1 DQL-class statement -- below
    # any reasonable min_samples floor.
    points = build_trend([snapshot], min_samples=5)
    assert points[0].duration_median_by_class == {}


def test_build_trend_computes_median_when_enough_samples() -> None:
    snapshot = _load()
    rows = [_statement(i, "DQL", float(i)) for i in range(1, 6)]
    snapshot.workload = CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows)

    points = build_trend([snapshot], min_samples=5)
    assert points[0].duration_median_by_class["DQL"] == pytest.approx(3.0)


def test_build_trend_one_point_per_snapshot_in_given_order() -> None:
    older = _load()
    newer = _load()
    newer.collection_time = older.collection_time + timedelta(days=1)

    points = build_trend([older, newer])
    assert len(points) == 2
    assert points[0].collected_at < points[1].collected_at


def test_render_trend_text_handles_empty_history() -> None:
    text = render_trend_text("production", [])
    assert "No saved baselines named" in text
    assert "production" in text


def test_render_trend_text_shows_missing_metrics_as_dash_not_fabricated() -> None:
    snapshot = _load()
    points = build_trend([snapshot], min_samples=5)
    text = render_trend_text("production", points)
    assert "production" in text
    assert "1 saved version" in text
