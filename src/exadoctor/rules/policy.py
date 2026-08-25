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
    # STORAGE-GROWTH-001: same lesson as every other trend/outlier rule
    # here -- a ratio-only check would flag a dev/test instance moving
    # from e.g. 0.2 GiB to 0.35 GiB (1.75x) as a WARNING for a clinically
    # meaningless absolute change. A few hundred MB of storage growth is
    # noise; 1.0 GiB is a defensible floor at the "small dev/test instance"
    # scale already used to justify the other rules' floors in this file.
    storage_growth_min_absolute_gib: float = 1.0
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
    # SYS-RESOURCE-TREND-001: latest day's value vs. the trailing-history
    # median for each metric, same shape as storage_growth_factor. Each
    # metric also needs its own absolute floor (units/scale differ a lot
    # between a CPU percentage and a MiB/s network rate) so a tiny baseline
    # can't turn a clinically meaningless move into a "3x" WARNING -- the
    # same lesson SQL-SLOW-001/SQL-TEMP-001 already learned the hard way.
    resource_trend_growth_factor: float = 1.5
    resource_trend_min_absolute_cpu_percent: float = 5.0
    resource_trend_min_absolute_temp_db_ram_mib: float = 50.0
    resource_trend_min_absolute_net_mib_per_sec: float = 5.0
    # SWAP has no "normal" baseline the way CPU/NET do -- Exasol's own
    # column comment says any SWAP above zero may indicate a system
    # configuration problem -- so its floor is intentionally the smallest
    # of the four: even a small amount of newly-appearing swap is worth a
    # WARNING, not just a large one.
    resource_trend_min_absolute_swap_mib_per_sec: float = 1.0
    # SESSION-AUTH-FAIL-001: a single failed login is often just a typo, but
    # this many failures from the same user/host pair within the window
    # looks like a stuck application retrying a stale credential, or a
    # brute-force attempt -- either way, worth a WARNING rather than INFO.
    failed_login_recurrence_threshold: int = 3
    # SESSION-TERMINATED-001: same recurrence framing as SQL-FAIL-001 --
    # occasional forced terminations (e.g. one idle-timeout) are routine;
    # many with the same error_code suggests a systemic connection-handling
    # issue (misconfigured timeout, app not closing connections) worth
    # flagging.
    forced_termination_recurrence_threshold: int = 3
    # SQL-WORKLOAD-TREND-001: same shape as resource_trend_growth_factor,
    # applied to daily statement volume/total execution time from
    # EXA_SQL_DAILY instead of system resource metrics.
    sql_workload_trend_growth_factor: float = 1.5
    # A ratio-only check on a near-idle instance would flag "10 statements
    # became 30" as a 3x WARNING for a clinically meaningless jump -- same
    # lesson as every other trend/outlier rule here. These floors are
    # deliberately low (an idle dev/test instance is a real, common case),
    # not tuned against any specific production workload.
    sql_workload_trend_min_absolute_count: float = 50.0
    sql_workload_trend_min_absolute_duration_seconds: float = 60.0


DEFAULT_POLICY = RulePolicy()
