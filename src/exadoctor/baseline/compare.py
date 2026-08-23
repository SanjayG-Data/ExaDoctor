"""Compare a saved baseline Snapshot against a freshly collected one
(roadmap Milestone 18: "Compare medians/percentiles/MAD for workload
trends").

Follows the same statistical philosophy as `exadoctor.rules.public_core`
(e.g. `evaluate_sql_slow`, `evaluate_sql_temp`, `evaluate_storage_growth`):
comparisons are relative to observed medians, not invented hard thresholds,
and a metric backed by too little data degrades to "not comparable" rather
than silently reporting "no change". `MIN_SAMPLES_FOR_COMPARISON` mirrors
`exadoctor.rules.policy.RulePolicy.min_samples_for_class_statistics`'s
default (5) but is kept as its own local constant -- the `baseline` package
does not otherwise depend on `rules`, and there's no shared product reason
the two sample-size floors must always move together.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from exadoctor.collectors.models import CollectionResult, DbSizeDailySample, SqlStatement
from exadoctor.models.snapshot import Snapshot

MIN_SAMPLES_FOR_COMPARISON = 5


@dataclass
class MetricComparison:
    """One comparable metric between a baseline and current snapshot.

    `comparable=False` means the change could not be computed at all
    (collector unavailable, or too few samples for a meaningful median) --
    this is deliberately distinct from a computed change of zero, so a
    caller/renderer can never confuse "no data" with "no change".

    `reason` is populated whenever `comparable` is False, explaining why.
    It may also be set when `comparable` is True to add context (e.g. the
    baseline median being exactly zero, which makes `relative_change_percent`
    undefined even though the absolute change is still meaningful).
    """

    metric: str
    unit: str
    baseline_value: float | None
    current_value: float | None
    absolute_change: float | None
    relative_change_percent: float | None
    comparable: bool
    reason: str | None = None
    baseline_samples: int | None = None
    current_samples: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "unit": self.unit,
            "baseline_value": self.baseline_value,
            "current_value": self.current_value,
            "absolute_change": self.absolute_change,
            "relative_change_percent": self.relative_change_percent,
            "comparable": self.comparable,
            "reason": self.reason,
            "baseline_samples": self.baseline_samples,
            "current_samples": self.current_samples,
        }


@dataclass
class ComparisonResult:
    baseline_collection_time: datetime
    current_collection_time: datetime
    # One entry per SqlStatement.command_class observed in either snapshot's
    # workload (e.g. "SELECT", "TRANSACTION") -- mirrors the per-class
    # grouping SQL-SLOW-001 uses, since duration distributions differ wildly
    # across command classes and a single overall median would blur that.
    duration_by_class: list[MetricComparison]
    temp_usage: MetricComparison
    storage: MetricComparison

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_collection_time": self.baseline_collection_time.isoformat(),
            "current_collection_time": self.current_collection_time.isoformat(),
            "duration_by_class": [m.to_dict() for m in self.duration_by_class],
            "temp_usage": self.temp_usage.to_dict(),
            "storage": self.storage.to_dict(),
        }


def _metric_change(
    metric: str,
    unit: str,
    baseline_value: float | None,
    current_value: float | None,
    *,
    baseline_samples: int | None = None,
    current_samples: int | None = None,
    unavailable_reason: str | None = None,
) -> MetricComparison:
    if unavailable_reason is not None:
        return MetricComparison(
            metric=metric,
            unit=unit,
            baseline_value=baseline_value,
            current_value=current_value,
            absolute_change=None,
            relative_change_percent=None,
            comparable=False,
            reason=unavailable_reason,
            baseline_samples=baseline_samples,
            current_samples=current_samples,
        )

    if baseline_value is None or current_value is None:
        return MetricComparison(
            metric=metric,
            unit=unit,
            baseline_value=baseline_value,
            current_value=current_value,
            absolute_change=None,
            relative_change_percent=None,
            comparable=False,
            reason="No usable value in the baseline and/or current snapshot.",
            baseline_samples=baseline_samples,
            current_samples=current_samples,
        )

    absolute_change = current_value - baseline_value
    relative_change_percent = (absolute_change / baseline_value * 100) if baseline_value != 0 else None
    reason = "Baseline value is zero; relative change is undefined." if baseline_value == 0 else None
    return MetricComparison(
        metric=metric,
        unit=unit,
        baseline_value=baseline_value,
        current_value=current_value,
        absolute_change=absolute_change,
        relative_change_percent=relative_change_percent,
        comparable=True,
        reason=reason,
        baseline_samples=baseline_samples,
        current_samples=current_samples,
    )


# These three are public (not module-private) because exadoctor.baseline.history
# reuses them to build a per-snapshot trend point across a whole saved
# history, not just a pairwise before/after comparison.


def group_durations_by_class(result: CollectionResult[SqlStatement]) -> dict[str, list[float]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for stmt in result.rows:
        if stmt.duration_seconds is not None and stmt.command_class:
            groups[stmt.command_class].append(stmt.duration_seconds)
    return groups


def temp_values(result: CollectionResult[SqlStatement]) -> list[float]:
    # Matches SQL-TEMP-001's filter: only statements that actually used TEMP.
    return [s.temp_db_ram_peak_mib for s in result.rows if s.temp_db_ram_peak_mib is not None and s.temp_db_ram_peak_mib > 0]


def latest_storage_gib(result: CollectionResult[DbSizeDailySample]) -> float | None:
    rows = sorted(
        (s for s in result.rows if s.storage_size_avg_gib is not None and s.interval_start is not None),
        key=lambda s: s.interval_start,
    )
    return rows[-1].storage_size_avg_gib if rows else None


def _compare_duration_by_class(baseline: Snapshot, current: Snapshot, min_samples: int) -> list[MetricComparison]:
    if not baseline.workload.available or not current.workload.available:
        reason = baseline.workload.reason if not baseline.workload.available else current.workload.reason
        return [
            _metric_change(
                "workload duration (all classes)",
                "seconds",
                None,
                None,
                unavailable_reason=reason or "EXA_SQL_LAST_DAY unavailable in the baseline and/or current snapshot.",
            )
        ]

    baseline_groups = group_durations_by_class(baseline.workload)
    current_groups = group_durations_by_class(current.workload)
    class_names = sorted(set(baseline_groups) | set(current_groups))

    changes: list[MetricComparison] = []
    for command_class in class_names:
        baseline_durations = baseline_groups.get(command_class, [])
        current_durations = current_groups.get(command_class, [])
        if len(baseline_durations) < min_samples or len(current_durations) < min_samples:
            changes.append(
                _metric_change(
                    f"workload duration ({command_class})",
                    "seconds",
                    None,
                    None,
                    baseline_samples=len(baseline_durations),
                    current_samples=len(current_durations),
                    unavailable_reason=(
                        f"Fewer than {min_samples} sample(s) for {command_class} in baseline "
                        f"({len(baseline_durations)}) or current ({len(current_durations)}); "
                        "a median comparison would not be meaningful."
                    ),
                )
            )
            continue
        changes.append(
            _metric_change(
                f"workload duration ({command_class})",
                "seconds",
                statistics.median(baseline_durations),
                statistics.median(current_durations),
                baseline_samples=len(baseline_durations),
                current_samples=len(current_durations),
            )
        )
    return changes


def _compare_temp_usage(baseline: Snapshot, current: Snapshot, min_samples: int) -> MetricComparison:
    if not baseline.workload.available or not current.workload.available:
        reason = baseline.workload.reason if not baseline.workload.available else current.workload.reason
        return _metric_change(
            "TEMP usage (median)",
            "MiB",
            None,
            None,
            unavailable_reason=reason or "EXA_SQL_LAST_DAY unavailable in the baseline and/or current snapshot.",
        )

    baseline_values = temp_values(baseline.workload)
    current_values = temp_values(current.workload)
    if len(baseline_values) < min_samples or len(current_values) < min_samples:
        return _metric_change(
            "TEMP usage (median)",
            "MiB",
            None,
            None,
            baseline_samples=len(baseline_values),
            current_samples=len(current_values),
            unavailable_reason=(
                f"Fewer than {min_samples} TEMP-using statement(s) in baseline ({len(baseline_values)}) "
                f"or current ({len(current_values)}); a median comparison would not be meaningful."
            ),
        )

    return _metric_change(
        "TEMP usage (median)",
        "MiB",
        statistics.median(baseline_values),
        statistics.median(current_values),
        baseline_samples=len(baseline_values),
        current_samples=len(current_values),
    )


def _compare_storage(baseline: Snapshot, current: Snapshot) -> MetricComparison:
    if not baseline.storage.available or not current.storage.available:
        reason = baseline.storage.reason if not baseline.storage.available else current.storage.reason
        return _metric_change(
            "storage size (latest daily avg)",
            "GiB",
            None,
            None,
            unavailable_reason=reason or "EXA_DB_SIZE_DAILY unavailable in the baseline and/or current snapshot.",
        )

    baseline_value = latest_storage_gib(baseline.storage)
    current_value = latest_storage_gib(current.storage)
    if baseline_value is None or current_value is None:
        return _metric_change(
            "storage size (latest daily avg)",
            "GiB",
            baseline_value,
            current_value,
            unavailable_reason="No EXA_DB_SIZE_DAILY sample with a usable value in the baseline and/or current snapshot.",
        )

    return _metric_change("storage size (latest daily avg)", "GiB", baseline_value, current_value)


def compare_snapshots(baseline: Snapshot, current: Snapshot, *, min_samples: int = MIN_SAMPLES_FOR_COMPARISON) -> ComparisonResult:
    """Compare `current` against `baseline`, computing median workload
    duration change per command class, median TEMP usage change, and latest
    storage size change.

    Never raises on missing/unavailable data: a `CollectionResult` with
    `available=False` (or with too few samples to trust a median) on either
    side simply produces a `comparable=False` `MetricComparison` for that
    metric, exactly as `rules.public_core` degrades to NOT_EVALUATED rather
    than a false PASS.
    """
    return ComparisonResult(
        baseline_collection_time=baseline.collection_time,
        current_collection_time=current.collection_time,
        duration_by_class=_compare_duration_by_class(baseline, current, min_samples),
        temp_usage=_compare_temp_usage(baseline, current, min_samples),
        storage=_compare_storage(baseline, current),
    )


def _render_metric_line(mc: MetricComparison, indent: str = "  ") -> list[str]:
    if not mc.comparable:
        return [f"{indent}[NOT COMPARABLE] {mc.metric}: {mc.reason}"]

    sign = "+" if mc.absolute_change is not None and mc.absolute_change >= 0 else ""
    if mc.relative_change_percent is not None:
        pct = f"{sign}{mc.relative_change_percent:.1f}%"
    else:
        pct = "n/a"
    line = (
        f"{indent}{mc.metric}: {mc.baseline_value:.3f} -> {mc.current_value:.3f} {mc.unit} "
        f"({sign}{mc.absolute_change:.3f} {mc.unit}, {pct})"
    )
    samples = ""
    if mc.baseline_samples is not None and mc.current_samples is not None:
        samples = f" [n={mc.baseline_samples} -> {mc.current_samples}]"
    lines = [line + samples]
    if mc.reason:
        lines.append(f"{indent}  note: {mc.reason}")
    return lines


def render_comparison_text(result: ComparisonResult) -> str:
    """Plain-text rendering of a `ComparisonResult`, following the tone of
    `exadoctor.report.terminal.render_scan_text`: every metric is shown,
    including ones that could not be compared, so missing data is never
    silently invisible."""
    lines = ["EXADOCTOR BASELINE COMPARISON", ""]
    lines.append(f"Baseline collected: {result.baseline_collection_time.isoformat()}")
    lines.append(f"Current collected:  {result.current_collection_time.isoformat()}")
    lines.append("")

    lines.append("WORKLOAD DURATION (median seconds, by command class)")
    if not result.duration_by_class:
        lines.append("  (no command classes observed in either snapshot)")
    for mc in result.duration_by_class:
        lines.extend(_render_metric_line(mc))
    lines.append("")

    lines.append("TEMP USAGE (median MiB)")
    lines.extend(_render_metric_line(result.temp_usage))
    lines.append("")

    lines.append("STORAGE SIZE (latest daily average GiB)")
    lines.extend(_render_metric_line(result.storage))

    return "\n".join(lines).rstrip() + "\n"
