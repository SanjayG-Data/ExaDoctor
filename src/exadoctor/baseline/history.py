"""Multi-point trend view across a baseline's saved history (roadmap
Milestone 18: "Persist local snapshots and trend metrics").

Reuses the exact per-snapshot metric extraction `compare.py` uses for a
pairwise before/after diff (median workload duration by class, median TEMP
usage, latest storage size), applied independently to every saved version
for one name rather than just two snapshots -- so a metric that's genuinely
missing/under-sampled at a given point in history is None there, not
fabricated, exactly matching compare.py's "never report a false no-change"
philosophy.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from exadoctor.baseline.compare import MIN_SAMPLES_FOR_COMPARISON, group_durations_by_class, latest_storage_gib, temp_values
from exadoctor.models.snapshot import Snapshot


@dataclass
class TrendPoint:
    collected_at: datetime
    storage_gib: float | None
    temp_usage_median_mib: float | None
    duration_median_by_class: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "collected_at": self.collected_at.isoformat(),
            "storage_gib": self.storage_gib,
            "temp_usage_median_mib": self.temp_usage_median_mib,
            "duration_median_by_class": dict(self.duration_median_by_class),
        }


def _snapshot_trend_point(snapshot: Snapshot, min_samples: int) -> TrendPoint:
    storage_gib = latest_storage_gib(snapshot.storage) if snapshot.storage.available else None

    values = temp_values(snapshot.workload) if snapshot.workload.available else []
    temp_median = statistics.median(values) if len(values) >= min_samples else None

    duration_median_by_class: dict[str, float] = {}
    if snapshot.workload.available:
        for command_class, durations in group_durations_by_class(snapshot.workload).items():
            if len(durations) >= min_samples:
                duration_median_by_class[command_class] = statistics.median(durations)

    return TrendPoint(
        collected_at=snapshot.collection_time,
        storage_gib=storage_gib,
        temp_usage_median_mib=temp_median,
        duration_median_by_class=duration_median_by_class,
    )


def build_trend(snapshots: list[Snapshot], min_samples: int = MIN_SAMPLES_FOR_COMPARISON) -> list[TrendPoint]:
    """One TrendPoint per snapshot, in the order given (callers pass
    oldest-first, per `load_baseline_history`'s ordering)."""
    return [_snapshot_trend_point(s, min_samples) for s in snapshots]


def render_trend_text(name: str, points: list[TrendPoint]) -> str:
    lines = [f"EXADOCTOR BASELINE HISTORY: {name}", ""]
    if not points:
        lines.append(f"No saved baselines named {name!r} yet. Run `exadoctor baseline create {name}` first.")
        return "\n".join(lines).rstrip() + "\n"

    lines.append(f"{len(points)} saved version(s), oldest first.")
    lines.append("")

    class_names = sorted({c for p in points for c in p.duration_median_by_class})
    # Column width per class must fit its own header text ("TRANSACTION
    # MEDIAN s" is longer than any duration value) plus a 2-space gutter --
    # a fixed width broke alignment for any command_class name over ~17
    # characters, running two columns together with no visible gap.
    class_labels = {c: f"{c} MEDIAN s" for c in class_names}
    class_widths = {c: max(len(label), 10) + 2 for c, label in class_labels.items()}

    # `collection_time` is always timezone-aware in a real Snapshot
    # (datetime.now(timezone.utc)), so its isoformat() is always 32 chars
    # (the "+00:00" suffix) -- fixed at 28 this column overflowed and threw
    # every later column out of alignment with its header.
    collected_width = max((len(p.collected_at.isoformat()) for p in points), default=19) + 2
    header = f"{'COLLECTED':<{collected_width}}{'STORAGE GiB':>13}{'TEMP MEDIAN MiB':>18}"
    for command_class in class_names:
        header += f"{class_labels[command_class]:>{class_widths[command_class]}}"
    lines.append(header)

    for point in points:
        storage = f"{point.storage_gib:.2f}" if point.storage_gib is not None else "-"
        temp = f"{point.temp_usage_median_mib:.1f}" if point.temp_usage_median_mib is not None else "-"
        row = f"{point.collected_at.isoformat():<{collected_width}}{storage:>13}{temp:>18}"
        for command_class in class_names:
            value = point.duration_median_by_class.get(command_class)
            row += f"{(f'{value:.3f}' if value is not None else '-'):>{class_widths[command_class]}}"
        lines.append(row)

    return "\n".join(lines).rstrip() + "\n"
