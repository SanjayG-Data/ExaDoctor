"""Public-core diagnostic rules (roadmap section 8.1).

Each rule reads only from a Snapshot -- never a gateway -- so a rule cannot
execute SQL by construction. Every rule degrades to NOT_EVALUATED rather
than PASS when its required source is unavailable or has too little data
for a meaningful judgement.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict

from exadoctor.models.finding import Evidence, Finding, FindingStatus, not_evaluated
from exadoctor.models.snapshot import Snapshot
from exadoctor.rules.engine import Rule
from exadoctor.rules.policy import RulePolicy

# Exasol's own error text embeds an incidental parse position, e.g.
# 'object X not found [line 1, column 27]' -- confirmed live that this
# position (and, for "object not found", the specific missing identifier)
# differs across otherwise-unrelated failures, which fragmented SQL-FAIL-001
# into singleton groups that could never reach the recurrence threshold.
# Stripping just the position suffix for the GROUPING key (never for the
# displayed text) fixes the position-only fragmentation without merging
# genuinely different failures that happen to share an error_code.
_ERROR_POSITION_SUFFIX_RE = re.compile(r"\s*\[line \d+, column \d+\]\s*$")


def _normalize_error_text_for_grouping(error_text: str | None) -> str | None:
    if error_text is None:
        return None
    return _ERROR_POSITION_SUFFIX_RE.sub("", error_text)


def evaluate_sys_swap(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    result = snapshot.monitoring
    if not result.available:
        return [
            not_evaluated(
                "SYS-SWAP-001",
                "Swap activity detected",
                "system",
                result.reason or "EXA_MONITOR_LAST_DAY unavailable",
                requirements=["EXA_MONITOR_LAST_DAY"],
            )
        ]

    samples = [(s.measure_time, s.swap_mib_per_sec) for s in result.rows if s.swap_mib_per_sec is not None]
    if not samples:
        return [
            not_evaluated(
                "SYS-SWAP-001",
                "Swap activity detected",
                "system",
                "No SWAP samples in the monitoring window.",
                requirements=["EXA_MONITOR_LAST_DAY"],
            )
        ]

    swapping = [(t, v) for t, v in samples if v > 0]
    if not swapping:
        return [
            Finding(
                id="SYS-SWAP-001",
                title="No swap activity",
                category="system",
                status=FindingStatus.PASS,
                summary=f"No swap activity observed across {len(samples)} monitoring sample(s).",
                confidence="HIGH",
                requirements=["EXA_MONITOR_LAST_DAY"],
                documentation=["Exasol documentation: EXA_MONITOR_LAST_DAY SWAP column"],
            )
        ]

    worst_time, worst_value = max(swapping, key=lambda pair: pair[1])
    return [
        Finding(
            id="SYS-SWAP-001",
            title="Swap activity detected",
            category="system",
            status=FindingStatus.WARNING,
            summary=(
                f"Swap activity observed in {len(swapping)} of {len(samples)} monitoring sample(s); "
                f"peak {worst_value} MiB/s at {worst_time.isoformat()}."
            ),
            evidence=[
                Evidence(
                    source="EXA_MONITOR_LAST_DAY",
                    stability="PUBLIC",
                    metric="SWAP",
                    value=worst_value,
                    unit="MiB/s",
                    timestamp=worst_time,
                    context=f"{len(swapping)}/{len(samples)} samples > 0",
                )
            ],
            recommendation=(
                "Investigate memory pressure; sustained swapping degrades performance. This source "
                "reports a cluster-maximum-style value and cannot identify which node is affected."
            ),
            confidence="HIGH",
            requirements=["EXA_MONITOR_LAST_DAY"],
            limitations=["EXA_MONITOR_LAST_DAY.SWAP is a cluster-maximum-style metric; it does not identify the affected node."],
            documentation=["Exasol documentation: EXA_MONITOR_LAST_DAY SWAP column"],
        )
    ]


def evaluate_sql_fail(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    result = snapshot.workload
    if not result.available:
        return [
            not_evaluated(
                "SQL-FAIL-001",
                "Repeated SQL errors",
                "workload",
                result.reason or "EXA_SQL_LAST_DAY unavailable",
                requirements=["EXA_SQL_LAST_DAY"],
            )
        ]

    failed = [s for s in result.rows if not s.success]
    if not failed:
        return [
            Finding(
                id="SQL-FAIL-001",
                title="No failed statements",
                category="workload",
                status=FindingStatus.PASS,
                summary=f"No failed statements among {len(result.rows)} statement(s) in the workload window.",
                confidence="HIGH",
                requirements=["EXA_SQL_LAST_DAY"],
            )
        ]

    groups: dict[tuple[str | None, str | None, str], list] = defaultdict(list)
    for s in failed:
        groups[(s.error_code, _normalize_error_text_for_grouping(s.error_text), s.command_name)].append(s)

    ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    findings: list[Finding] = []
    for (error_code, _normalized_error_text, command_name), items in ranked[: policy.max_findings_per_rule]:
        severity = FindingStatus.WARNING if len(items) >= policy.error_recurrence_threshold else FindingStatus.INFO
        with_time = [i for i in items if i.start_time is not None]
        latest = max(with_time, key=lambda i: i.start_time) if with_time else None
        # Display the most recent occurrence's actual (non-normalized) text
        # -- normalization is a grouping-key concern only, never shown.
        error_text = latest.error_text if latest is not None else items[0].error_text
        session_count = len({i.session_id for i in items})
        findings.append(
            Finding(
                id="SQL-FAIL-001",
                title="Repeated SQL errors" if severity == FindingStatus.WARNING else "SQL error observed",
                category="workload",
                status=severity,
                summary=(
                    f"{len(items)} occurrence(s) across {session_count} session(s) of {command_name} "
                    f"failing with error_code={error_code!r}: {error_text}"
                ),
                evidence=[
                    Evidence(
                        source="EXA_SQL_LAST_DAY",
                        stability="PUBLIC",
                        metric="ERROR_COUNT",
                        value=len(items),
                        unit="occurrences",
                        timestamp=latest.start_time if latest else None,
                        context=f"error_code={error_code}",
                    )
                ],
                recommendation=(
                    "Investigate this recurring failure; it affects multiple sessions/statements and may be systemic."
                    if severity == FindingStatus.WARNING
                    else "Isolated failure observed; may be expected user/application error."
                ),
                confidence="HIGH",
                requirements=["EXA_SQL_LAST_DAY"],
                limitations=[
                    "EXA_SQL_LAST_DAY does not expose user identity or full SQL text, only COMMAND_NAME/ERROR_CODE/ERROR_TEXT."
                ],
                documentation=["ExaDoctor policy: recurrence threshold distinguishing WARNING from INFO"],
            )
        )

    if len(ranked) > policy.max_findings_per_rule:
        skipped = len(ranked) - policy.max_findings_per_rule
        findings.append(
            Finding(
                id="SQL-FAIL-001",
                title="Additional distinct errors not shown",
                category="workload",
                status=FindingStatus.INFO,
                summary=f"{skipped} additional distinct error group(s) were not reported individually (capped at {policy.max_findings_per_rule}).",
                confidence="HIGH",
                documentation=["ExaDoctor policy: per-rule finding cap"],
            )
        )
    return findings


def evaluate_sql_slow(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    result = snapshot.workload
    if not result.available:
        return [
            not_evaluated(
                "SQL-SLOW-001",
                "Duration outlier",
                "workload",
                result.reason or "EXA_SQL_LAST_DAY unavailable",
                requirements=["EXA_SQL_LAST_DAY"],
            )
        ]

    by_class: dict[str, list] = defaultdict(list)
    for s in result.rows:
        if s.duration_seconds is not None and s.command_class:
            by_class[s.command_class].append(s)

    findings: list[Finding] = []
    for command_class, items in sorted(by_class.items()):
        if len(items) < policy.min_samples_for_class_statistics:
            continue
        durations = [i.duration_seconds for i in items]
        median = statistics.median(durations)
        if median <= 0:
            continue
        threshold = median * policy.duration_outlier_factor
        # Ratio alone flags clinically meaningless differences in a fast
        # class (0.001s -> 0.045s is "45x the median" but not worth a
        # WARNING) -- confirmed live in exadoctor scan's own output. Require
        # the absolute gap over the median to also clear a floor.
        outliers = [
            i
            for i in items
            if i.duration_seconds > threshold
            # round() before the >= floor check: DURATION is DECIMAL(12,3), so
            # any gap "genuinely at" the floor is exact to 3 decimal places --
            # comparing the raw float subtraction is IEEE-754-unstable (e.g.
            # 0.12 - 0.02 == 0.09999999999999999, not 0.1), which made a case
            # that should exactly clear the documented >= boundary silently
            # fail it. Found by independent QA.
            and round(i.duration_seconds - median, 3) >= policy.duration_outlier_min_absolute_seconds
        ]
        if not outliers:
            continue
        worst = max(outliers, key=lambda i: i.duration_seconds)
        findings.append(
            Finding(
                id="SQL-SLOW-001",
                title=f"Duration outlier in {command_class} statements",
                category="workload",
                status=FindingStatus.WARNING,
                summary=(
                    f"{len(outliers)} of {len(items)} {command_class} statement(s) ran at or above "
                    f"{policy.duration_outlier_factor:g}x the class median ({median:.3f}s); "
                    f"worst was {worst.duration_seconds:.3f}s."
                ),
                evidence=[
                    Evidence(
                        source="EXA_SQL_LAST_DAY",
                        stability="PUBLIC",
                        metric="DURATION",
                        value=worst.duration_seconds,
                        unit="seconds",
                        timestamp=worst.start_time,
                        context=f"class={command_class} median={median:.3f}s n={len(items)}",
                        session_id=worst.session_id,
                        stmt_id=worst.stmt_id,
                    )
                ],
                recommendation=(
                    "Review the outlier statement(s) for plan regressions, blocking waits, or unusually "
                    "large inputs relative to peers in the same command class."
                ),
                confidence="MEDIUM",
                requirements=["EXA_SQL_LAST_DAY"],
                limitations=[
                    f"Outlier is relative to other {command_class} statements observed in this window only, not a universal threshold."
                ],
                documentation=["ExaDoctor policy: median-relative outlier factor"],
            )
        )

    if not findings:
        return [
            Finding(
                id="SQL-SLOW-001",
                title="No duration outliers",
                category="workload",
                status=FindingStatus.PASS,
                summary="No statement exceeded the median-relative duration threshold for its command class.",
                confidence="MEDIUM",
                requirements=["EXA_SQL_LAST_DAY"],
                documentation=["ExaDoctor policy: median-relative outlier factor"],
            )
        ]
    return findings


def evaluate_sql_temp(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    result = snapshot.workload
    if not result.available:
        return [
            not_evaluated(
                "SQL-TEMP-001",
                "TEMP-heavy statement outlier",
                "workload",
                result.reason or "EXA_SQL_LAST_DAY unavailable",
                requirements=["EXA_SQL_LAST_DAY"],
            )
        ]

    items = [s for s in result.rows if s.temp_db_ram_peak_mib is not None and s.temp_db_ram_peak_mib > 0]
    if len(items) < policy.min_samples_for_class_statistics:
        return [
            Finding(
                id="SQL-TEMP-001",
                title="Not enough TEMP usage data",
                category="workload",
                status=FindingStatus.NOT_EVALUATED,
                summary=f"Only {len(items)} statement(s) used TEMP memory; too few for a distribution comparison.",
                confidence="LOW",
                requirements=["EXA_SQL_LAST_DAY"],
                limitations=["Fewer than the minimum sample count for a meaningful outlier comparison."],
            )
        ]

    values = [s.temp_db_ram_peak_mib for s in items]
    median = statistics.median(values)
    if median <= 0:
        return [
            Finding(
                id="SQL-TEMP-001",
                title="No significant TEMP usage",
                category="workload",
                status=FindingStatus.PASS,
                summary="TEMP memory usage is negligible across the workload window.",
                confidence="MEDIUM",
                requirements=["EXA_SQL_LAST_DAY"],
            )
        ]

    threshold = median * policy.temp_outlier_factor
    outliers = [
        s
        for s in items
        if s.temp_db_ram_peak_mib > threshold
        # round() before the >= floor check: TEMP_DB_RAM_PEAK is
        # DECIMAL(10,1), so the same IEEE-754 instability fixed above for
        # SQL-SLOW-001 applies here too. Found by independent QA.
        and round(s.temp_db_ram_peak_mib - median, 1) >= policy.temp_outlier_min_absolute_mib
    ]
    if not outliers:
        return [
            Finding(
                id="SQL-TEMP-001",
                title="No TEMP-heavy outliers",
                category="workload",
                status=FindingStatus.PASS,
                summary=f"No statement exceeded {policy.temp_outlier_factor:g}x the workload's TEMP usage median ({median:.1f} MiB).",
                confidence="MEDIUM",
                requirements=["EXA_SQL_LAST_DAY"],
                documentation=["ExaDoctor policy: median-relative outlier factor"],
            )
        ]

    worst = max(outliers, key=lambda s: s.temp_db_ram_peak_mib)
    return [
        Finding(
            id="SQL-TEMP-001",
            title="TEMP-heavy statement outlier",
            category="workload",
            status=FindingStatus.WARNING,
            summary=(
                f"{len(outliers)} of {len(items)} TEMP-using statement(s) exceeded "
                f"{policy.temp_outlier_factor:g}x the median TEMP usage ({median:.1f} MiB); "
                f"worst used {worst.temp_db_ram_peak_mib:.1f} MiB."
            ),
            evidence=[
                Evidence(
                    source="EXA_SQL_LAST_DAY",
                    stability="PUBLIC",
                    metric="TEMP_DB_RAM_PEAK",
                    value=worst.temp_db_ram_peak_mib,
                    unit="MiB",
                    timestamp=worst.start_time,
                    context=f"median={median:.1f} MiB n={len(items)}",
                    session_id=worst.session_id,
                    stmt_id=worst.stmt_id,
                )
            ],
            recommendation=(
                "Review the outlier statement(s) for large sorts/joins/aggregations spilling to TEMP; "
                "consider indexing, filtering earlier, or splitting the statement."
            ),
            confidence="MEDIUM",
            requirements=["EXA_SQL_LAST_DAY"],
            limitations=["Outlier is relative to this workload window's own TEMP usage distribution, not an absolute capacity judgement."],
            documentation=["ExaDoctor policy: median-relative outlier factor"],
        )
    ]


def evaluate_sql_remote(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    result = snapshot.workload
    if not result.available:
        return [
            not_evaluated(
                "SQL-REMOTE-001",
                "Remote-storage-heavy statement",
                "workload",
                result.reason or "EXA_SQL_LAST_DAY unavailable",
                requirements=["EXA_SQL_LAST_DAY"],
            )
        ]

    items = [s for s in result.rows if s.remote_read_size_mib is not None and s.remote_read_size_mib > 0]
    # `total_remote <= 0` was previously checked here alongside `not items`,
    # but it's unreachable when `items` is non-empty (it's a sum of
    # strictly-positive values by the filter above) -- `not items` alone is
    # the real condition; the old compound check just confused a reader
    # into thinking there was a second, independent case here.
    if not items:
        return [
            Finding(
                id="SQL-REMOTE-001",
                title="No remote storage reads",
                category="workload",
                status=FindingStatus.PASS,
                summary="No statement read from remote storage in the workload window.",
                confidence="HIGH",
                requirements=["EXA_SQL_LAST_DAY"],
            )
        ]

    total_remote = sum(s.remote_read_size_mib for s in items)

    ranked = sorted(items, key=lambda s: s.remote_read_size_mib, reverse=True)
    top = ranked[: min(5, len(ranked))]
    top_share = sum(s.remote_read_size_mib for s in top) / total_remote * 100
    worst = ranked[0]
    return [
        Finding(
            id="SQL-REMOTE-001",
            title="Remote-storage-heavy statement(s)",
            category="workload",
            status=FindingStatus.INFO,
            summary=(
                f"Top {len(top)} statement(s) account for {top_share:.0f}% of {total_remote:.1f} MiB total "
                f"remote reads in the window; largest single read was {worst.remote_read_size_mib:.1f} MiB."
            ),
            evidence=[
                Evidence(
                    source="EXA_SQL_LAST_DAY",
                    stability="PUBLIC",
                    metric="REMOTE_READ_SIZE",
                    value=worst.remote_read_size_mib,
                    unit="MiB",
                    timestamp=worst.start_time,
                    context=f"top-{len(top)} share={top_share:.0f}% of total {total_remote:.1f} MiB",
                    session_id=worst.session_id,
                    stmt_id=worst.stmt_id,
                )
            ],
            recommendation="Remote reads are not inherently a fault; review only if unexpected for this workload or contributing to latency.",
            confidence="MEDIUM",
            requirements=["EXA_SQL_LAST_DAY"],
            limitations=["Remote-storage usage can be an expected, deliberate part of the workload (e.g. object storage as a data source)."],
            documentation=["ExaDoctor policy: report top contributors to remote I/O, informational only"],
        )
    ]


def evaluate_sys_temp(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    result = snapshot.monitoring
    if not result.available:
        return [
            not_evaluated(
                "SYS-TEMP-001",
                "TEMP usage anomaly",
                "system",
                result.reason or "EXA_MONITOR_LAST_DAY unavailable",
                requirements=["EXA_MONITOR_LAST_DAY"],
            )
        ]

    samples = [(s.measure_time, s.temp_db_ram_mib) for s in result.rows if s.temp_db_ram_mib is not None]
    if len(samples) < policy.min_samples_for_class_statistics:
        return [
            Finding(
                id="SYS-TEMP-001",
                title="Not enough TEMP monitoring data",
                category="system",
                status=FindingStatus.NOT_EVALUATED,
                summary=f"Only {len(samples)} TEMP_DB_RAM sample(s) in the monitoring window.",
                confidence="LOW",
                requirements=["EXA_MONITOR_LAST_DAY"],
            )
        ]

    values = [v for _, v in samples]
    median = statistics.median(values)
    if median <= 0:
        return [
            Finding(
                id="SYS-TEMP-001",
                title="Negligible TEMP usage",
                category="system",
                status=FindingStatus.PASS,
                summary="TEMP memory usage is negligible across the monitoring window.",
                confidence="MEDIUM",
                requirements=["EXA_MONITOR_LAST_DAY"],
            )
        ]

    spike_threshold = median * policy.monitor_spike_factor
    persistence_threshold = median * policy.monitor_persistence_factor
    spikes = [(t, v) for t, v in samples if v > spike_threshold]
    sustained = [(t, v) for t, v in samples if v > persistence_threshold]
    sustained_fraction = len(sustained) / len(samples)

    findings: list[Finding] = []
    if spikes:
        worst_time, worst_value = max(spikes, key=lambda pair: pair[1])
        findings.append(
            Finding(
                id="SYS-TEMP-001",
                title="TEMP usage spike",
                category="system",
                status=FindingStatus.WARNING,
                summary=(
                    f"{len(spikes)} of {len(samples)} sample(s) spiked above "
                    f"{policy.monitor_spike_factor:g}x the window median ({median:.1f} MiB); "
                    f"peak {worst_value:.1f} MiB at {worst_time.isoformat()}."
                ),
                evidence=[
                    Evidence(
                        source="EXA_MONITOR_LAST_DAY",
                        stability="PUBLIC",
                        metric="TEMP_DB_RAM",
                        value=worst_value,
                        unit="MiB",
                        timestamp=worst_time,
                        context=f"median={median:.1f} MiB n={len(samples)}",
                    )
                ],
                recommendation="Investigate what ran during the spike (correlate with EXA_SQL_LAST_DAY by time window).",
                confidence="MEDIUM",
                requirements=["EXA_MONITOR_LAST_DAY"],
                documentation=["ExaDoctor policy: median-relative spike factor"],
            )
        )
    if sustained_fraction >= policy.monitor_persistence_fraction:
        findings.append(
            Finding(
                id="SYS-TEMP-001",
                title="Sustained elevated TEMP usage",
                category="system",
                status=FindingStatus.WARNING,
                summary=(
                    f"TEMP usage stayed above {policy.monitor_persistence_factor:g}x the window median "
                    f"for {sustained_fraction * 100:.0f}% of samples."
                ),
                evidence=[
                    Evidence(
                        source="EXA_MONITOR_LAST_DAY",
                        stability="PUBLIC",
                        metric="TEMP_DB_RAM",
                        value=sustained_fraction,
                        unit="fraction of samples",
                        timestamp=None,
                        context=f"median={median:.1f} MiB n={len(samples)}",
                    )
                ],
                recommendation=(
                    "Sustained (not just spiky) elevated TEMP usage may indicate persistent workload pressure "
                    "rather than a one-off statement; review recurring heavy queries."
                ),
                confidence="MEDIUM",
                requirements=["EXA_MONITOR_LAST_DAY"],
                documentation=["ExaDoctor policy: persistence fraction/factor thresholds"],
            )
        )
    if not findings:
        findings.append(
            Finding(
                id="SYS-TEMP-001",
                title="No TEMP usage anomaly",
                category="system",
                status=FindingStatus.PASS,
                summary=f"TEMP usage stayed within {policy.monitor_spike_factor:g}x of the window median across {len(samples)} sample(s).",
                confidence="MEDIUM",
                requirements=["EXA_MONITOR_LAST_DAY"],
                documentation=["ExaDoctor policy: median-relative spike/persistence thresholds"],
            )
        )
    return findings


def evaluate_storage_growth(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    result = snapshot.storage
    if not result.available:
        return [
            not_evaluated(
                "STORAGE-GROWTH-001",
                "Unusual database growth",
                "capacity",
                result.reason or "EXA_DB_SIZE_DAILY unavailable",
                requirements=["EXA_DB_SIZE_DAILY"],
            )
        ]

    rows = sorted(
        (s for s in result.rows if s.storage_size_avg_gib is not None and s.interval_start is not None),
        key=lambda s: s.interval_start,
    )
    if len(rows) < policy.min_samples_for_class_statistics:
        return [
            Finding(
                id="STORAGE-GROWTH-001",
                title="Not enough storage history",
                category="capacity",
                status=FindingStatus.NOT_EVALUATED,
                summary=f"Only {len(rows)} day(s) of EXA_DB_SIZE_DAILY history available; too few for a trend comparison.",
                confidence="LOW",
                requirements=["EXA_DB_SIZE_DAILY"],
            )
        ]

    latest = rows[-1]
    history = rows[:-1]
    baseline = statistics.median(s.storage_size_avg_gib for s in history)
    if baseline <= 0:
        return [
            Finding(
                id="STORAGE-GROWTH-001",
                title="Negligible storage baseline",
                category="capacity",
                status=FindingStatus.NOT_EVALUATED,
                summary="Historical storage size baseline is zero or negative; cannot compute a meaningful growth ratio.",
                confidence="LOW",
                requirements=["EXA_DB_SIZE_DAILY"],
            )
        ]

    ratio = latest.storage_size_avg_gib / baseline
    if ratio < policy.storage_growth_factor:
        return [
            Finding(
                id="STORAGE-GROWTH-001",
                title="Storage growth within trend",
                category="capacity",
                status=FindingStatus.PASS,
                summary=(
                    f"Latest storage size ({latest.storage_size_avg_gib:.1f} GiB) is {ratio:.2f}x the "
                    f"{len(history)}-day historical median ({baseline:.1f} GiB)."
                ),
                confidence="MEDIUM",
                requirements=["EXA_DB_SIZE_DAILY"],
                documentation=["ExaDoctor policy: relative growth threshold vs. trailing median"],
            )
        ]

    return [
        Finding(
            id="STORAGE-GROWTH-001",
            title="Unusual database growth",
            category="capacity",
            status=FindingStatus.WARNING,
            summary=(
                f"Latest storage size ({latest.storage_size_avg_gib:.1f} GiB) is {ratio:.2f}x the "
                f"{len(history)}-day historical median ({baseline:.1f} GiB), exceeding the "
                f"{policy.storage_growth_factor:g}x growth threshold."
            ),
            evidence=[
                Evidence(
                    source="EXA_DB_SIZE_DAILY",
                    stability="PUBLIC",
                    metric="STORAGE_SIZE_AVG",
                    value=latest.storage_size_avg_gib,
                    unit="GiB",
                    timestamp=latest.interval_start,
                    context=f"historical median={baseline:.1f} GiB over {len(history)} day(s)",
                )
            ],
            recommendation=(
                "Review what changed recently (bulk loads, new objects, retention changes) and confirm "
                "this growth is expected before it affects capacity planning."
            ),
            confidence="MEDIUM",
            requirements=["EXA_DB_SIZE_DAILY"],
            limitations=["Trend-relative to this instance's own recent history, not an absolute capacity judgement."],
            documentation=["ExaDoctor policy: relative growth threshold vs. trailing median"],
        )
    ]


def evaluate_session_long(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    result = snapshot.sessions
    if not result.available:
        return [
            not_evaluated(
                "SESSION-LONG-001",
                "Long-lived session",
                "sessions",
                result.reason or "EXA_ALL_SESSIONS unavailable",
                requirements=["EXA_ALL_SESSIONS"],
            )
        ]

    reference_time = snapshot.database_time
    if reference_time is None:
        return [
            Finding(
                id="SESSION-LONG-001",
                title="Cannot evaluate session age",
                category="sessions",
                status=FindingStatus.NOT_EVALUATED,
                summary="Database reference time (CURRENT_TIMESTAMP) could not be determined; session age cannot be computed reliably.",
                confidence="LOW",
                requirements=["EXA_ALL_SESSIONS"],
                limitations=[
                    "Session age requires the database's own current time as a reference to avoid "
                    "clock-skew/timezone mismatch with the collecting host."
                ],
            )
        ]

    long_sessions = []
    for s in result.rows:
        if s.login_time is None:
            continue
        age_seconds = (reference_time - s.login_time).total_seconds()
        if age_seconds >= policy.long_session_threshold_seconds:
            long_sessions.append((s, age_seconds))

    if not long_sessions:
        return [
            Finding(
                id="SESSION-LONG-001",
                title="No long-lived sessions",
                category="sessions",
                status=FindingStatus.PASS,
                summary=(
                    f"No session exceeded the {policy.long_session_threshold_seconds / 3600:.1f}h age "
                    f"threshold among {len(result.rows)} open session(s)."
                ),
                confidence="HIGH",
                requirements=["EXA_ALL_SESSIONS"],
                documentation=["ExaDoctor policy: long-session age threshold"],
            )
        ]

    long_sessions.sort(key=lambda pair: pair[1], reverse=True)
    findings: list[Finding] = []
    for session, age_seconds in long_sessions[: policy.max_findings_per_rule]:
        findings.append(
            Finding(
                id="SESSION-LONG-001",
                title="Long-lived session",
                category="sessions",
                status=FindingStatus.INFO,
                summary=(
                    f"Session {session.session_id} (user={session.user_name}, status={session.status}) has "
                    f"been open for {age_seconds / 3600:.1f}h, exceeding the "
                    f"{policy.long_session_threshold_seconds / 3600:.1f}h policy threshold."
                ),
                evidence=[
                    Evidence(
                        source="EXA_ALL_SESSIONS",
                        stability="PUBLIC",
                        metric="SESSION_AGE",
                        value=age_seconds,
                        unit="seconds",
                        timestamp=session.login_time,
                        context=f"status={session.status}",
                        session_id=session.session_id,
                    )
                ],
                recommendation=(
                    "A long-lived session is not inherently a problem, but review whether it is intentional "
                    "(e.g. a pooled connection) or an orphaned/idle session holding resources."
                ),
                confidence="HIGH",
                requirements=["EXA_ALL_SESSIONS"],
                limitations=[
                    "Session age is measured from LOGIN_TIME to the database's current time; it does not "
                    "indicate whether the session is idle or active."
                ],
                documentation=["ExaDoctor policy: long-session age threshold (user-configurable)"],
            )
        )
    if len(long_sessions) > policy.max_findings_per_rule:
        skipped = len(long_sessions) - policy.max_findings_per_rule
        findings.append(
            Finding(
                id="SESSION-LONG-001",
                title="Additional long-lived sessions not shown",
                category="sessions",
                status=FindingStatus.INFO,
                summary=f"{skipped} additional long-lived session(s) were not reported individually (capped at {policy.max_findings_per_rule}).",
                confidence="HIGH",
                documentation=["ExaDoctor policy: per-rule finding cap"],
            )
        )
    return findings


PUBLIC_CORE_RULES: list[Rule] = [
    Rule(id="SYS-SWAP-001", title="Swap activity detected", category="system", evaluate=evaluate_sys_swap),
    Rule(id="SQL-FAIL-001", title="Repeated SQL errors", category="workload", evaluate=evaluate_sql_fail),
    Rule(id="SQL-SLOW-001", title="Duration outlier", category="workload", evaluate=evaluate_sql_slow),
    Rule(id="SQL-TEMP-001", title="TEMP-heavy statement outlier", category="workload", evaluate=evaluate_sql_temp),
    Rule(id="SQL-REMOTE-001", title="Remote-storage-heavy statement", category="workload", evaluate=evaluate_sql_remote),
    Rule(id="SYS-TEMP-001", title="TEMP usage anomaly", category="system", evaluate=evaluate_sys_temp),
    Rule(id="STORAGE-GROWTH-001", title="Unusual database growth", category="capacity", evaluate=evaluate_storage_growth),
    Rule(id="SESSION-LONG-001", title="Long-lived session", category="sessions", evaluate=evaluate_session_long),
]
