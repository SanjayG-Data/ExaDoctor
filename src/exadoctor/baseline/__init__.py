"""Local baseline persistence and trend comparison (roadmap Milestones 17-18).

`store` persists named Snapshots to a local SQLite file; `compare` computes
median-based workload/storage trend differences between two Snapshots;
`history` builds a multi-point trend view across all saved versions of one
named baseline.
"""

from __future__ import annotations

from exadoctor.baseline.compare import ComparisonResult, MetricComparison, compare_snapshots, render_comparison_text
from exadoctor.baseline.history import TrendPoint, build_trend, render_trend_text
from exadoctor.baseline.store import (
    BASELINE_DB_VAR,
    DEFAULT_BASELINE_DB_PATH,
    BaselineRecord,
    list_baselines,
    load_baseline,
    load_baseline_history,
    resolve_baseline_db_path,
    save_baseline,
)

__all__ = [
    "BASELINE_DB_VAR",
    "DEFAULT_BASELINE_DB_PATH",
    "BaselineRecord",
    "ComparisonResult",
    "MetricComparison",
    "TrendPoint",
    "build_trend",
    "compare_snapshots",
    "list_baselines",
    "load_baseline",
    "load_baseline_history",
    "render_comparison_text",
    "render_trend_text",
    "resolve_baseline_db_path",
    "save_baseline",
]
