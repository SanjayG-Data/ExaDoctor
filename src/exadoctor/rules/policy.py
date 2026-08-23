"""ExaDoctor policy thresholds for rules that need one.

Every threshold here is an ExaDoctor product decision, not an Exasol
behavior -- roadmap section 8.3 requires every recommendation to state
whether it comes from verified Exasol guidance, a reviewed knowledge rule,
or ExaDoctor policy. Rules using these cite "ExaDoctor policy" in their
Finding.documentation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RulePolicy:
    long_session_threshold_seconds: float = 3600.0
    min_samples_for_class_statistics: int = 5
    duration_outlier_factor: float = 3.0
    # A ratio-only outlier check fires on clinically meaningless differences
    # in a fast/small class (e.g. 0.001s -> 0.045s is "45x the median" but
    # not worth a WARNING) -- confirmed live in exadoctor scan's own output.
    # The outlier's absolute gap over the median must also clear this floor.
    duration_outlier_min_absolute_seconds: float = 0.1
    temp_outlier_factor: float = 3.0
    temp_outlier_min_absolute_mib: float = 10.0
    monitor_spike_factor: float = 3.0
    monitor_persistence_fraction: float = 0.5
    monitor_persistence_factor: float = 1.5
    storage_growth_factor: float = 1.5
    error_recurrence_threshold: int = 3
    max_findings_per_rule: int = 25
    dominant_part_share_threshold: float = 0.5
    temp_materialize_mib_threshold: float = 100.0
    # Cumulative transaction-conflict wait time as a share of total workload
    # duration in the same window -- mirrors the same "share of total
    # duration" framing SQL-FAIL-001/PERF-BOTTLENECK-001 already use, applied
    # to EXA_DBA_TRANSACTION_CONFLICTS instead of profile parts.
    transaction_conflict_share_threshold: float = 1.0
    # Inclusion bar for SQL-COMMAND-SHARE-001's per-command-name ranking: a
    # command_name is worth naming if it accounts for at least this share of
    # total workload duration OR total CPU-seconds, whichever comes first --
    # matches the two concrete numbers found in the legacy ikar4us tool's own
    # ranking query (duration_sum_% > 0.5 or cpu_sum_% > 1.0).
    command_share_duration_threshold_percent: float = 0.5
    command_share_cpu_threshold_percent: float = 1.0


DEFAULT_POLICY = RulePolicy()
