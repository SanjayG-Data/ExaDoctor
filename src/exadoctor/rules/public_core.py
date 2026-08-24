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
                "TEMP spillover for large sorts/joins/aggregations is expected Exasol behavior, not "
                "inherently a fault -- per Exasol's docs, intermediate results that don't fit in DB RAM are "
                "designed to spill to TEMP. Review the outlier statement(s) only if this pattern is "
                "unexpected for this workload; if TEMP pressure shows up often, check the SYS-RAM-SIZING-001 "
                "finding (Exasol's own recommended DB RAM) before assuming a per-query problem."
            ),
            confidence="MEDIUM",
            requirements=["EXA_SQL_LAST_DAY"],
            limitations=[
                "Outlier is relative to this workload window's own TEMP usage distribution, not an absolute "
                "capacity judgement -- see SYS-RAM-SIZING-001 for Exasol's own sizing recommendation."
            ],
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


def evaluate_command_share(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    """Reports which COMMAND_NAME(s) dominate total workload time/CPU in the
    window -- a workload-*composition* view, distinct from SQL-SLOW-001's
    per-statement outlier detection (a command_name can dominate the total
    without any single statement of that type being an outlier, e.g. many
    unremarkable SELECTs simply outnumbering everything else).

    Adapted from the legacy ikar4us tool's own ranking query, with one
    deliberate correctness fix: EXA_SQL_LAST_DAY.CPU is documented as "CPU
    usage as percentage of total system CPU resources available" -- an
    instantaneous utilization reading, not a magnitude -- so summing it
    directly across statements (as the legacy tool did) would let a command
    class with many short, low-duration-but-momentarily-busy statements look
    like it used more CPU than one with fewer, longer, steadily-busy
    statements. CPU% * duration_seconds (a CPU-seconds proxy) is summed
    instead, which is comparable regardless of how many statements make up
    each group.

    Always INFO, same as SQL-REMOTE-001: dominating the workload isn't
    inherently a fault, just a composition fact worth knowing.
    """
    result = snapshot.workload
    if not result.available:
        return [
            not_evaluated(
                "SQL-COMMAND-SHARE-001",
                "Workload composition by command",
                "workload",
                result.reason or "EXA_SQL_LAST_DAY unavailable",
                requirements=["EXA_SQL_LAST_DAY"],
            )
        ]

    items = [s for s in result.rows if s.duration_seconds is not None and s.command_name]
    if not items:
        return [
            Finding(
                id="SQL-COMMAND-SHARE-001",
                title="No workload activity",
                category="workload",
                status=FindingStatus.PASS,
                summary="No statements with a usable duration in the workload window.",
                confidence="HIGH",
                requirements=["EXA_SQL_LAST_DAY"],
            )
        ]

    total_duration = sum(s.duration_seconds for s in items)
    total_cpu_seconds = sum(
        s.cpu_percent / 100 * s.duration_seconds for s in items if s.cpu_percent is not None
    )

    by_command: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])  # [duration, cpu_seconds, count]
    for s in items:
        stats = by_command[s.command_name]
        stats[0] += s.duration_seconds
        if s.cpu_percent is not None:
            stats[1] += s.cpu_percent / 100 * s.duration_seconds
        stats[2] += 1

    contributors = []
    for command_name, (duration, cpu_seconds, count) in by_command.items():
        duration_share = (duration / total_duration * 100) if total_duration > 0 else 0.0
        cpu_share = (cpu_seconds / total_cpu_seconds * 100) if total_cpu_seconds > 0 else 0.0
        if (
            duration_share >= policy.command_share_duration_threshold_percent
            or cpu_share >= policy.command_share_cpu_threshold_percent
        ):
            contributors.append((command_name, duration, duration_share, cpu_seconds, cpu_share, count))

    if not contributors:
        return [
            Finding(
                id="SQL-COMMAND-SHARE-001",
                title="No single command type dominates the workload",
                category="workload",
                status=FindingStatus.PASS,
                summary=(
                    f"No COMMAND_NAME reached {policy.command_share_duration_threshold_percent:g}% of total "
                    f"duration or {policy.command_share_cpu_threshold_percent:g}% of total CPU-seconds across "
                    f"{len(items)} statement(s) -- workload time is spread across many command types."
                ),
                confidence="MEDIUM",
                requirements=["EXA_SQL_LAST_DAY"],
                documentation=["ExaDoctor policy: share-of-total-duration/CPU threshold"],
            )
        ]

    contributors.sort(key=lambda c: c[1], reverse=True)
    top = contributors[: min(5, len(contributors))]
    lines = [
        f"{name} ({count} stmt(s)): {duration_share:.1f}% duration, {cpu_share:.1f}% CPU-seconds"
        for name, duration, duration_share, cpu_seconds, cpu_share, count in top
    ]
    worst_name, worst_duration, worst_duration_share, worst_cpu_seconds, worst_cpu_share, worst_count = top[0]

    return [
        Finding(
            id="SQL-COMMAND-SHARE-001",
            title="Workload composition by command",
            category="workload",
            status=FindingStatus.INFO,
            summary=(
                f"{len(top)} of {len(by_command)} distinct command type(s) account for a meaningful share of "
                f"the workload; top contributor is {worst_name} ({worst_count} stmt(s), "
                f"{worst_duration_share:.1f}% of total duration, {worst_cpu_share:.1f}% of total CPU-seconds). "
                + "; ".join(lines)
            ),
            evidence=[
                Evidence(
                    source="EXA_SQL_LAST_DAY",
                    stability="PUBLIC",
                    metric="DURATION/CPU",
                    value=worst_duration,
                    unit="seconds",
                    timestamp=None,
                    context=(
                        f"{worst_name}: {worst_duration_share:.1f}% of {total_duration:.1f}s total duration, "
                        f"{worst_cpu_share:.1f}% of {total_cpu_seconds:.1f} total CPU-seconds"
                    ),
                )
            ],
            recommendation=(
                "Not inherently a fault -- this is workload composition, not an anomaly. Useful context when "
                "planning capacity or investigating a slow window: which command types actually dominate "
                "total time/CPU, as opposed to any single outlier statement (see SQL-SLOW-001)."
            ),
            confidence="MEDIUM",
            requirements=["EXA_SQL_LAST_DAY"],
            limitations=[
                "CPU share is derived as CPU% * DURATION per statement (a CPU-seconds proxy), not a direct "
                "Exasol-reported total -- EXA_SQL_LAST_DAY.CPU is an instantaneous utilization percentage, "
                "not summable across statements on its own."
            ],
            documentation=["ExaDoctor policy: share-of-total-duration/CPU threshold"],
        )
    ]


def evaluate_transaction_conflicts(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    """Reports lock/commit-wait contention from EXA_DBA_TRANSACTION_CONFLICTS
    -- registered in the capability probe since Milestone 0 but never read by
    any collector or rule until now. This is a distinct bottleneck class from
    every other workload rule here: concurrency contention between sessions
    (one transaction waiting on another to commit), not plan/data-movement
    inefficiency within a single statement.

    Expresses total conflict wait time as a share of total workload duration
    in the same window, mirroring the same "share of total duration" framing
    SQL-FAIL-001/PERF-BOTTLENECK-001 already use elsewhere. Requires
    SELECT ANY DICTIONARY (see docs/privileges.md) -- degrades to
    NOT_EVALUATED without it, same as the other privilege-gated sources.
    """
    result = snapshot.transaction_conflicts
    if not result.available:
        return [
            not_evaluated(
                "SQL-CONFLICT-001",
                "Transaction conflict contention",
                "workload",
                result.reason or "EXA_DBA_TRANSACTION_CONFLICTS unavailable",
                requirements=["EXA_DBA_TRANSACTION_CONFLICTS"],
            )
        ]

    if not result.rows:
        return [
            Finding(
                id="SQL-CONFLICT-001",
                title="No transaction conflicts",
                category="workload",
                status=FindingStatus.PASS,
                summary="No transaction conflicts (e.g. WAIT FOR COMMIT) observed in the workload window.",
                confidence="HIGH",
                requirements=["EXA_DBA_TRANSACTION_CONFLICTS"],
            )
        ]

    closed = [c for c in result.rows if c.stop_time is not None]
    open_count = len(result.rows) - len(closed)
    total_conflict_seconds = sum((c.stop_time - c.start_time).total_seconds() for c in closed)

    by_object: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])  # [count, seconds]
    for c in closed:
        key = c.conflict_objects or "(unknown object)"
        by_object[key][0] += 1
        by_object[key][1] += (c.stop_time - c.start_time).total_seconds()
    worst_object, worst_stats = (
        max(by_object.items(), key=lambda kv: kv[1][1]) if by_object else (None, [0.0, 0.0])
    )

    workload_result = snapshot.workload
    total_workload_seconds = (
        sum(s.duration_seconds for s in workload_result.rows if s.duration_seconds is not None)
        if workload_result.available
        else None
    )
    conflict_share_percent = (
        (total_conflict_seconds / total_workload_seconds * 100)
        if total_workload_seconds and total_workload_seconds > 0
        else None
    )

    evidence = [
        Evidence(
            source="EXA_DBA_TRANSACTION_CONFLICTS",
            stability="PUBLIC",
            metric="CONFLICT_DURATION",
            value=total_conflict_seconds,
            unit="seconds",
            timestamp=max(c.start_time for c in result.rows),
            context=(
                f"{len(result.rows)} conflict(s), {open_count} still open, worst object="
                f"{worst_object!r} ({worst_stats[0]:g} conflicts, {worst_stats[1]:.1f}s)"
            ),
        )
    ]
    limitations = [
        "Conflict count/duration is windowed to the last day, same as EXA_SQL_LAST_DAY, for a comparable "
        "share calculation -- older conflicts (this table does not roll off after 24h on its own) are not "
        "included."
    ]
    if open_count:
        limitations.append(
            f"{open_count} conflict(s) had no STOP_TIME at collection time (still open or unresolved when "
            "collected) and are excluded from the duration total."
        )

    if conflict_share_percent is None:
        return [
            Finding(
                id="SQL-CONFLICT-001",
                title="Transaction conflicts observed",
                category="workload",
                status=FindingStatus.INFO,
                summary=(
                    f"{len(result.rows)} transaction conflict(s) totaling {total_conflict_seconds:.1f}s of wait "
                    f"time; workload duration was unavailable, so a share-of-total could not be computed."
                ),
                evidence=evidence,
                recommendation=(
                    f"Review contention on {worst_object!r} if this recurs; EXA_SQL_LAST_DAY was unavailable "
                    "so this could not be expressed as a share of total workload time."
                ),
                confidence="MEDIUM",
                requirements=["EXA_DBA_TRANSACTION_CONFLICTS"],
                limitations=limitations,
                documentation=["ExaDoctor policy: share-of-total-duration threshold"],
            )
        ]

    if conflict_share_percent < policy.transaction_conflict_share_threshold:
        return [
            Finding(
                id="SQL-CONFLICT-001",
                title="Transaction conflicts within normal range",
                category="workload",
                status=FindingStatus.PASS,
                summary=(
                    f"{len(result.rows)} transaction conflict(s) totaling {total_conflict_seconds:.1f}s "
                    f"({conflict_share_percent:.2f}% of total workload duration) -- below the "
                    f"{policy.transaction_conflict_share_threshold:g}% threshold."
                ),
                evidence=evidence,
                confidence="MEDIUM",
                requirements=["EXA_DBA_TRANSACTION_CONFLICTS", "EXA_SQL_LAST_DAY"],
                limitations=limitations,
                documentation=["ExaDoctor policy: share-of-total-duration threshold"],
            )
        ]

    return [
        Finding(
            id="SQL-CONFLICT-001",
            title="Transaction conflict contention",
            category="workload",
            status=FindingStatus.WARNING,
            summary=(
                f"{len(result.rows)} transaction conflict(s) totaling {total_conflict_seconds:.1f}s "
                f"({conflict_share_percent:.2f}% of total workload duration) -- at or above the "
                f"{policy.transaction_conflict_share_threshold:g}% threshold. Worst-contended object: "
                f"{worst_object!r} ({worst_stats[0]:g} conflicts, {worst_stats[1]:.1f}s)."
            ),
            evidence=evidence,
            recommendation=(
                "Sessions are spending meaningful time waiting on each other's commits/locks -- this is "
                "concurrency contention, distinct from a slow query plan. Review transaction boundaries and "
                f"commit frequency around {worst_object!r}, and whether conflicting sessions could be "
                "serialized or batched instead of contending."
            ),
            confidence="MEDIUM",
            requirements=["EXA_DBA_TRANSACTION_CONFLICTS", "EXA_SQL_LAST_DAY"],
            limitations=limitations,
            documentation=["ExaDoctor policy: share-of-total-duration threshold"],
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
                recommendation=(
                    "A brief spike is often one large sort/join/aggregation temporarily spilling to TEMP -- "
                    "expected Exasol behavior, not inherently a fault. Correlate with EXA_SQL_LAST_DAY by "
                    "time window to see what ran; check SYS-RAM-SIZING-001 if spikes are frequent."
                ),
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
                    "Sustained (not just spiky) elevated TEMP usage suggests persistent workload pressure "
                    "rather than a one-off statement; review recurring heavy queries, and check "
                    "SYS-RAM-SIZING-001 (Exasol's own recommended DB RAM) to see whether this cluster is "
                    "sized for that pressure."
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


# (metric attribute, display name, unit, policy absolute-floor attribute)
_RESOURCE_TREND_METRICS = (
    ("cpu_avg_percent", "CPU", "%", "resource_trend_min_absolute_cpu_percent"),
    ("temp_db_ram_avg_mib", "TEMP DB RAM", "MiB", "resource_trend_min_absolute_temp_db_ram_mib"),
    ("net_avg_mib_per_sec", "network", "MiB/s", "resource_trend_min_absolute_net_mib_per_sec"),
    ("swap_avg_mib_per_sec", "swap", "MiB/s", "resource_trend_min_absolute_swap_mib_per_sec"),
)


def evaluate_resource_trend(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    """Multi-day resource trend, using EXA_MONITOR_DAILY -- a source this
    project didn't know existed until a user explicitly asked whether every
    EXA_* table had actually been audited (it hadn't; see IMPLEMENTATION_
    HISTORY.md). SYS-SWAP-001/SYS-TEMP-001 only ever look at the current
    24-hour window (EXA_MONITOR_LAST_DAY); this looks at whether a metric's
    *daily* average has been trending up over the trailing history, which a
    24-hour-only check structurally cannot see.

    Same statistical shape as STORAGE-GROWTH-001 (latest day vs.
    trailing-history median, ratio-based), applied to four metrics instead
    of one, each with its own absolute floor since a CPU percentage and a
    MiB/s network rate aren't on comparable scales. When the trailing
    median is exactly zero (a ratio is undefined), the absolute floor alone
    decides -- this matters most for swap, where zero is the normal,
    healthy baseline and any newly-appearing amount is itself the signal,
    not a ratio off of it.
    """
    result = snapshot.monitor_daily
    if not result.available:
        return [
            not_evaluated(
                "SYS-RESOURCE-TREND-001",
                "Resource usage trend",
                "system",
                result.reason or "EXA_MONITOR_DAILY unavailable",
                requirements=["EXA_MONITOR_DAILY"],
            )
        ]

    rows = sorted((s for s in result.rows if s.interval_start is not None), key=lambda s: s.interval_start)
    if len(rows) < policy.min_samples_for_class_statistics:
        return [
            Finding(
                id="SYS-RESOURCE-TREND-001",
                title="Not enough daily history",
                category="system",
                status=FindingStatus.NOT_EVALUATED,
                summary=f"Only {len(rows)} day(s) of EXA_MONITOR_DAILY history available; too few for a trend comparison.",
                confidence="LOW",
                requirements=["EXA_MONITOR_DAILY"],
            )
        ]

    latest = rows[-1]
    history = rows[:-1]

    findings: list[Finding] = []
    for attr, display_name, unit, floor_attr in _RESOURCE_TREND_METRICS:
        latest_value = getattr(latest, attr)
        history_values = [v for s in history if (v := getattr(s, attr)) is not None]
        if latest_value is None or len(history_values) < policy.min_samples_for_class_statistics - 1:
            continue

        baseline = statistics.median(history_values)
        floor = getattr(policy, floor_attr)
        ratio = latest_value / baseline if baseline > 0 else None

        if ratio is not None:
            is_trending_up = ratio >= policy.resource_trend_growth_factor and (latest_value - baseline) >= floor
            comparison_phrase = f"{ratio:.2f}x the"
        else:
            # Undefined ratio from a zero baseline -- the absolute floor
            # alone decides (see docstring: this is exactly the swap case).
            is_trending_up = latest_value >= floor
            comparison_phrase = "newly above the (previously zero)"

        if not is_trending_up:
            continue

        findings.append(
            Finding(
                id="SYS-RESOURCE-TREND-001",
                title=f"{display_name} usage trending up",
                category="system",
                status=FindingStatus.WARNING,
                summary=(
                    f"Latest day's {display_name} average ({latest_value:.1f} {unit}) is "
                    f"{comparison_phrase} {len(history_values)}-day historical median ({baseline:.1f} {unit})."
                ),
                evidence=[
                    Evidence(
                        source="EXA_MONITOR_DAILY",
                        stability="PUBLIC",
                        metric=attr.upper(),
                        value=latest_value,
                        unit=unit,
                        timestamp=latest.interval_start,
                        context=f"historical median={baseline:.1f} {unit} over {len(history_values)} day(s)",
                    )
                ],
                recommendation=(
                    f"Review what changed recently for {display_name} usage; a sustained upward trend across "
                    "days (not just a single spike) suggests growing workload pressure rather than a one-off "
                    "event -- see SYS-RAM-SIZING-001 if this is CPU or TEMP DB RAM related."
                ),
                confidence="MEDIUM",
                requirements=["EXA_MONITOR_DAILY"],
                limitations=[
                    "Trend-relative to this instance's own recent daily history, not an absolute capacity judgement."
                ],
                documentation=["ExaDoctor policy: relative growth threshold vs. trailing daily median"],
            )
        )

    if not findings:
        return [
            Finding(
                id="SYS-RESOURCE-TREND-001",
                title="No resource usage trending up",
                category="system",
                status=FindingStatus.PASS,
                summary=(
                    f"None of CPU/TEMP DB RAM/network/swap trended up beyond "
                    f"{policy.resource_trend_growth_factor:g}x the trailing {len(history)}-day median."
                ),
                confidence="MEDIUM",
                requirements=["EXA_MONITOR_DAILY"],
                documentation=["ExaDoctor policy: relative growth threshold vs. trailing daily median"],
            )
        ]
    return findings


_SIZING_DOC_URL = "https://docs.exasol.com/db/latest/administration/on-premise/sizing.htm"


def evaluate_ram_sizing(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    """Compares Exasol's own recommended DB RAM (`EXA_DB_SIZE_DAILY.
    RECOMMENDED_DB_RAM_SIZE_AVG`) against the cluster's actually provisioned
    DB RAM (`EXA_SYSTEM_EVENTS.DB_RAM_SIZE`, documented by Exasol as "Used DB
    RAM license in GiB") -- both collected since Milestone 3/this addition,
    but never compared by any rule until now.

    Per Exasol's own sizing documentation (see _SIZING_DOC_URL), this is the
    documented way to check DB RAM sizing "if you have a running system", and
    the recommendation formula already bakes in TEMP headroom (their worked
    example uses 5% of compressed data volume) -- i.e. Exasol expects some
    TEMP usage by design, not as an anomaly. That's also why SQL-TEMP-001/
    SYS-TEMP-001 point here before assuming a per-query problem.

    Falls back to an INFO-only report of the recommendation (this rule's
    original behavior) if EXA_SYSTEM_EVENTS is unavailable/empty -- older
    Exasol versions or a restricted user might not expose it, and reporting
    only the recommended figure is still useful even without the comparison.
    """
    storage_result = snapshot.storage
    if not storage_result.available:
        return [
            not_evaluated(
                "SYS-RAM-SIZING-001",
                "Exasol-recommended DB RAM",
                "capacity",
                storage_result.reason or "EXA_DB_SIZE_DAILY unavailable",
                requirements=["EXA_DB_SIZE_DAILY"],
            )
        ]

    storage_rows = sorted(
        (s for s in storage_result.rows if s.recommended_db_ram_size_avg_gib is not None and s.interval_start is not None),
        key=lambda s: s.interval_start,
    )
    if not storage_rows:
        return [
            Finding(
                id="SYS-RAM-SIZING-001",
                title="No DB RAM recommendation available",
                category="capacity",
                status=FindingStatus.NOT_EVALUATED,
                summary="EXA_DB_SIZE_DAILY has no row with a RECOMMENDED_DB_RAM_SIZE_AVG value in this window.",
                confidence="LOW",
                requirements=["EXA_DB_SIZE_DAILY"],
            )
        ]
    recommended = storage_rows[-1]

    events_result = snapshot.system_events
    actual_events = (
        sorted(
            (e for e in events_result.rows if e.db_ram_size_gib is not None),
            key=lambda e: e.measure_time,
        )
        if events_result.available
        else []
    )

    if not actual_events:
        return [
            Finding(
                id="SYS-RAM-SIZING-001",
                title="Exasol-recommended DB RAM",
                category="capacity",
                status=FindingStatus.INFO,
                summary=(
                    f"Exasol's own sizing calculation recommends {recommended.recommended_db_ram_size_avg_gib:.1f} "
                    f"GiB of DB RAM for this cluster's current data volume, including TEMP headroom, as of "
                    f"{recommended.interval_start.date().isoformat()}."
                ),
                evidence=[
                    Evidence(
                        source="EXA_DB_SIZE_DAILY",
                        stability="PUBLIC",
                        metric="RECOMMENDED_DB_RAM_SIZE_AVG",
                        value=recommended.recommended_db_ram_size_avg_gib,
                        unit="GiB",
                        timestamp=recommended.interval_start,
                        context="Exasol's own DB RAM sizing recommendation, including TEMP headroom",
                    )
                ],
                recommendation=(
                    "Compare this figure against your cluster's actually provisioned DB RAM -- "
                    f"EXA_SYSTEM_EVENTS was unavailable, so ExaDoctor could not do that comparison itself. "
                    f"See Exasol's sizing guide: {_SIZING_DOC_URL}"
                ),
                confidence="HIGH",
                requirements=["EXA_DB_SIZE_DAILY"],
                limitations=[
                    "This is Exasol's own sizing recommendation, not an ExaDoctor-invented threshold. "
                    "EXA_SYSTEM_EVENTS (the source for actually-provisioned DB RAM) was unavailable, so this "
                    "is informational only, not a pass/fail judgement."
                ],
                documentation=["Exasol official sizing documentation: RECOMMENDED_DB_RAM_SIZE_* columns"],
            )
        ]

    actual = actual_events[-1]
    gap = actual.db_ram_size_gib - recommended.recommended_db_ram_size_avg_gib
    if actual.db_ram_size_gib >= recommended.recommended_db_ram_size_avg_gib:
        return [
            Finding(
                id="SYS-RAM-SIZING-001",
                title="DB RAM meets Exasol's recommendation",
                category="capacity",
                status=FindingStatus.PASS,
                summary=(
                    f"Provisioned DB RAM ({actual.db_ram_size_gib:.1f} GiB) meets or exceeds Exasol's own "
                    f"recommendation ({recommended.recommended_db_ram_size_avg_gib:.1f} GiB, as of "
                    f"{recommended.interval_start.date().isoformat()})."
                ),
                evidence=[
                    Evidence(
                        source="EXA_SYSTEM_EVENTS",
                        stability="PUBLIC",
                        metric="DB_RAM_SIZE",
                        value=actual.db_ram_size_gib,
                        unit="GiB",
                        timestamp=actual.measure_time,
                        context=f"recommended={recommended.recommended_db_ram_size_avg_gib:.1f} GiB",
                    )
                ],
                confidence="HIGH",
                requirements=["EXA_DB_SIZE_DAILY", "EXA_SYSTEM_EVENTS"],
                documentation=["Exasol official sizing documentation: RECOMMENDED_DB_RAM_SIZE_* / DB_RAM_SIZE columns"],
            )
        ]

    return [
        Finding(
            id="SYS-RAM-SIZING-001",
            title="DB RAM below Exasol's recommendation",
            category="capacity",
            status=FindingStatus.WARNING,
            summary=(
                f"Provisioned DB RAM ({actual.db_ram_size_gib:.1f} GiB) is {-gap:.1f} GiB below Exasol's own "
                f"recommendation ({recommended.recommended_db_ram_size_avg_gib:.1f} GiB, as of "
                f"{recommended.interval_start.date().isoformat()})."
            ),
            evidence=[
                Evidence(
                    source="EXA_SYSTEM_EVENTS",
                    stability="PUBLIC",
                    metric="DB_RAM_SIZE",
                    value=actual.db_ram_size_gib,
                    unit="GiB",
                    timestamp=actual.measure_time,
                    context=f"recommended={recommended.recommended_db_ram_size_avg_gib:.1f} GiB",
                )
            ],
            recommendation=(
                "Provisioned DB RAM is below Exasol's own recommendation, which already includes TEMP "
                "headroom -- TEMP-heavy statements and TEMP usage spikes elsewhere in this report are more "
                f"likely a capacity issue than a per-query one. See Exasol's sizing guide: {_SIZING_DOC_URL}"
            ),
            confidence="HIGH",
            requirements=["EXA_DB_SIZE_DAILY", "EXA_SYSTEM_EVENTS"],
            limitations=[
                "Recommendation is based on the latest available EXA_DB_SIZE_DAILY row's data volume; "
                "actual RAM is the most recent EXA_SYSTEM_EVENTS entry -- both are Exasol's own reported "
                "figures, not ExaDoctor-invented thresholds."
            ],
            documentation=["Exasol official sizing documentation: RECOMMENDED_DB_RAM_SIZE_* / DB_RAM_SIZE columns"],
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


def evaluate_session_auth_failures(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    """Reports failed login attempts from EXA_DBA_SESSIONS_LAST_DAY --
    invisible to every other rule here, since EXA_ALL_SESSIONS/EXA_DBA_
    SESSIONS only ever list currently-open (i.e. successfully authenticated)
    sessions. A failed login never opens a session at all, so it can only be
    seen in this table's own SUCCESS column.

    Grouped by (user_name, host) and ranked by count, same shape as
    SQL-FAIL-001: an isolated failure is likely a typo, but repeated
    failures from the same user/host pair within the window is the
    signature of a stuck application retrying a stale credential, or a
    brute-force attempt.
    """
    result = snapshot.session_history
    if not result.available:
        return [
            not_evaluated(
                "SESSION-AUTH-FAIL-001",
                "Failed login attempts",
                "sessions",
                result.reason or "EXA_DBA_SESSIONS_LAST_DAY unavailable",
                requirements=["EXA_DBA_SESSIONS_LAST_DAY"],
            )
        ]

    failed = [r for r in result.rows if not r.success]
    if not failed:
        return [
            Finding(
                id="SESSION-AUTH-FAIL-001",
                title="No failed login attempts",
                category="sessions",
                status=FindingStatus.PASS,
                summary=f"No failed login attempts among {len(result.rows)} login attempt(s) in the last day.",
                confidence="HIGH",
                requirements=["EXA_DBA_SESSIONS_LAST_DAY"],
            )
        ]

    groups: dict[tuple[str | None, str | None], list] = defaultdict(list)
    for r in failed:
        groups[(r.user_name, r.host)].append(r)

    ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    findings: list[Finding] = []
    for (user_name, host), items in ranked[: policy.max_findings_per_rule]:
        severity = FindingStatus.WARNING if len(items) >= policy.failed_login_recurrence_threshold else FindingStatus.INFO
        with_time = [i for i in items if i.login_time is not None]
        latest = max(with_time, key=lambda i: i.login_time) if with_time else items[0]
        findings.append(
            Finding(
                id="SESSION-AUTH-FAIL-001",
                title="Repeated failed login attempts" if severity == FindingStatus.WARNING else "Failed login attempt",
                category="sessions",
                status=severity,
                summary=(
                    f"{len(items)} failed login attempt(s) for user={user_name!r} from host={host!r}"
                    f"{f'; latest error_code={latest.error_code!r}: {latest.error_text}' if latest.error_code else ''}."
                ),
                evidence=[
                    Evidence(
                        source="EXA_DBA_SESSIONS_LAST_DAY",
                        stability="PUBLIC",
                        metric="FAILED_LOGIN_COUNT",
                        value=len(items),
                        unit="occurrences",
                        timestamp=latest.login_time,
                        context=f"user={user_name} host={host}",
                    )
                ],
                recommendation=(
                    "Multiple failed logins from the same user/host may indicate a misconfigured application "
                    "retrying a stale credential, or an unauthorized access attempt -- review the source."
                    if severity == FindingStatus.WARNING
                    else "Isolated failed login; may be expected (e.g. a user mistyping a password)."
                ),
                confidence="HIGH",
                requirements=["EXA_DBA_SESSIONS_LAST_DAY"],
                limitations=["EXA_DBA_SESSIONS_LAST_DAY is a 24-hour rolling window; older attempts are not visible."],
                documentation=["ExaDoctor policy: recurrence threshold distinguishing WARNING from INFO"],
            )
        )

    if len(ranked) > policy.max_findings_per_rule:
        skipped = len(ranked) - policy.max_findings_per_rule
        findings.append(
            Finding(
                id="SESSION-AUTH-FAIL-001",
                title="Additional failed-login groups not shown",
                category="sessions",
                status=FindingStatus.INFO,
                summary=f"{skipped} additional user/host group(s) with failed logins were not reported individually (capped at {policy.max_findings_per_rule}).",
                confidence="HIGH",
                documentation=["ExaDoctor policy: per-rule finding cap"],
            )
        )
    return findings


def evaluate_session_forced_termination(snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    """Reports sessions from EXA_DBA_SESSIONS_LAST_DAY that logged in
    successfully but were forcefully terminated (ERROR_CODE populated on an
    otherwise-successful login) -- e.g. an idle timeout, an admin KILL
    SESSION, or a network drop. EXA_ALL_SESSIONS/EXA_DBA_SESSIONS cannot see
    this either: once a session ends, it simply disappears from those
    tables, successful or not.

    Grouped by ERROR_CODE, same recurrence framing as SQL-FAIL-001: one
    idle-timeout is routine; many with the same code suggests a systemic
    connection-handling issue rather than an isolated event.
    """
    result = snapshot.session_history
    if not result.available:
        return [
            not_evaluated(
                "SESSION-TERMINATED-001",
                "Forced session termination",
                "sessions",
                result.reason or "EXA_DBA_SESSIONS_LAST_DAY unavailable",
                requirements=["EXA_DBA_SESSIONS_LAST_DAY"],
            )
        ]

    terminated = [r for r in result.rows if r.success and r.error_code]
    if not terminated:
        return [
            Finding(
                id="SESSION-TERMINATED-001",
                title="No forced session terminations",
                category="sessions",
                status=FindingStatus.PASS,
                summary=f"No forcefully terminated sessions among {len(result.rows)} session(s) in the last day.",
                confidence="HIGH",
                requirements=["EXA_DBA_SESSIONS_LAST_DAY"],
            )
        ]

    groups: dict[str, list] = defaultdict(list)
    for r in terminated:
        groups[r.error_code].append(r)

    ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    findings: list[Finding] = []
    for error_code, items in ranked[: policy.max_findings_per_rule]:
        severity = (
            FindingStatus.WARNING if len(items) >= policy.forced_termination_recurrence_threshold else FindingStatus.INFO
        )
        with_time = [i for i in items if i.logout_time is not None]
        latest = max(with_time, key=lambda i: i.logout_time) if with_time else items[0]
        findings.append(
            Finding(
                id="SESSION-TERMINATED-001",
                title="Recurring forced session terminations" if severity == FindingStatus.WARNING else "Forced session termination",
                category="sessions",
                status=severity,
                summary=(
                    f"{len(items)} session(s) forcefully terminated with error_code={error_code!r}: {latest.error_text}"
                ),
                evidence=[
                    Evidence(
                        source="EXA_DBA_SESSIONS_LAST_DAY",
                        stability="PUBLIC",
                        metric="FORCED_TERMINATION_COUNT",
                        value=len(items),
                        unit="occurrences",
                        timestamp=latest.logout_time,
                        context=f"error_code={error_code}",
                        session_id=latest.session_id,
                    )
                ],
                recommendation=(
                    "A recurring forced-termination code suggests a systemic issue (e.g. an idle timeout that's "
                    "too aggressive for this workload, or an application not closing connections) rather than "
                    "an isolated event -- review connection handling and timeout settings."
                    if severity == FindingStatus.WARNING
                    else "Occasional forced terminations (e.g. a single idle timeout) are routine, not inherently a fault."
                ),
                confidence="MEDIUM",
                requirements=["EXA_DBA_SESSIONS_LAST_DAY"],
                limitations=[
                    "EXA_DBA_SESSIONS_LAST_DAY is a 24-hour rolling window; older terminations are not visible.",
                    "ERROR_CODE/ERROR_TEXT come from Exasol's own session termination reporting; ExaDoctor does "
                    "not further classify which codes are benign vs. concerning.",
                ],
                documentation=["ExaDoctor policy: recurrence threshold distinguishing WARNING from INFO"],
            )
        )

    if len(ranked) > policy.max_findings_per_rule:
        skipped = len(ranked) - policy.max_findings_per_rule
        findings.append(
            Finding(
                id="SESSION-TERMINATED-001",
                title="Additional forced-termination groups not shown",
                category="sessions",
                status=FindingStatus.INFO,
                summary=f"{skipped} additional error_code group(s) were not reported individually (capped at {policy.max_findings_per_rule}).",
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
    Rule(id="SQL-COMMAND-SHARE-001", title="Workload composition by command", category="workload", evaluate=evaluate_command_share),
    Rule(id="SQL-CONFLICT-001", title="Transaction conflict contention", category="workload", evaluate=evaluate_transaction_conflicts),
    Rule(id="SYS-TEMP-001", title="TEMP usage anomaly", category="system", evaluate=evaluate_sys_temp),
    Rule(id="SYS-RESOURCE-TREND-001", title="Resource usage trend", category="system", evaluate=evaluate_resource_trend),
    Rule(id="STORAGE-GROWTH-001", title="Unusual database growth", category="capacity", evaluate=evaluate_storage_growth),
    Rule(id="SYS-RAM-SIZING-001", title="Exasol-recommended DB RAM", category="capacity", evaluate=evaluate_ram_sizing),
    Rule(id="SESSION-LONG-001", title="Long-lived session", category="sessions", evaluate=evaluate_session_long),
    Rule(id="SESSION-AUTH-FAIL-001", title="Failed login attempts", category="sessions", evaluate=evaluate_session_auth_failures),
    Rule(id="SESSION-TERMINATED-001", title="Forced session termination", category="sessions", evaluate=evaluate_session_forced_termination),
]
