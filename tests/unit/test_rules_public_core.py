from datetime import datetime, timedelta

from rules_helpers import (
    DB_TIME,
    db_size_sample,
    make_snapshot,
    monitor_daily_sample,
    monitor_sample,
    session_info,
    sql_statement,
    system_event,
    transaction_conflict,
    unavailable_monitor_daily,
    unavailable_monitoring,
    unavailable_sessions,
    unavailable_storage,
    unavailable_system_events,
    unavailable_transaction_conflicts,
    unavailable_workload,
)

from exadoctor.models.finding import FindingStatus
from exadoctor.rules.policy import DEFAULT_POLICY
from exadoctor.rules.public_core import (
    evaluate_command_share,
    evaluate_ram_sizing,
    evaluate_resource_trend,
    evaluate_session_long,
    evaluate_sql_fail,
    evaluate_sql_remote,
    evaluate_sql_slow,
    evaluate_sql_temp,
    evaluate_storage_growth,
    evaluate_sys_swap,
    evaluate_sys_temp,
    evaluate_transaction_conflicts,
)


# ---- SYS-SWAP-001 -----------------------------------------------------


def test_sys_swap_not_evaluated_when_monitoring_unavailable():
    snapshot = make_snapshot(monitoring=unavailable_monitoring())
    findings = evaluate_sys_swap(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_sys_swap_passes_when_no_swap():
    rows = [monitor_sample(DB_TIME, swap_mib_per_sec=0.0) for _ in range(3)]
    from exadoctor.collectors.models import CollectionResult

    snapshot = make_snapshot(monitoring=CollectionResult("EXA_MONITOR_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sys_swap(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_sys_swap_warns_when_swap_observed():
    from exadoctor.collectors.models import CollectionResult

    rows = [monitor_sample(DB_TIME, swap_mib_per_sec=0.0), monitor_sample(DB_TIME, swap_mib_per_sec=5.0)]
    snapshot = make_snapshot(monitoring=CollectionResult("EXA_MONITOR_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sys_swap(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.WARNING
    assert findings[0].evidence[0].value == 5.0


# ---- SQL-FAIL-001 -------------------------------------------------------


def test_sql_fail_not_evaluated_when_workload_unavailable():
    snapshot = make_snapshot(workload=unavailable_workload())
    findings = evaluate_sql_fail(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_sql_fail_passes_when_no_failures():
    from exadoctor.collectors.models import CollectionResult

    rows = [sql_statement(1, 1, success=True)]
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_fail(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_sql_fail_below_recurrence_threshold_is_info_not_warning():
    from exadoctor.collectors.models import CollectionResult

    rows = [sql_statement(1, 1, success=False, error_code="E1", error_text="boom")]
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_fail(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.INFO


def test_sql_fail_at_recurrence_threshold_is_warning():
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.error_recurrence_threshold
    rows = [sql_statement(i, 1, success=False, error_code="E1", error_text="boom") for i in range(n)]
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_fail(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.WARNING


def test_sql_fail_recurrence_ignores_incidental_line_column_position():
    # Real bug found via independent code review, confirmed live against
    # exadoctor's own Milestone-0 probe failures: Exasol's "object not
    # found" errors embed a parse position ("[line 1, column 27]") that
    # differs across every occurrence of the SAME underlying missing-object
    # reference, fragmenting what should be one recurring group into
    # singletons that never reach the recurrence threshold.
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.error_recurrence_threshold
    rows = [
        sql_statement(
            i,
            1,
            success=False,
            error_code="42000",
            error_text=f'object SYS."$EXA_PROFILE_LAST_DAY" not found [line 1, column {20 + i}]',
        )
        for i in range(n)
    ]
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_fail(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.WARNING
    assert len(findings) == 1  # grouped into one, not N singleton findings


def test_sql_fail_recurrence_still_separates_genuinely_different_errors():
    # The fix must not over-merge: two different missing objects should
    # remain two separate (INFO, isolated) findings, not one WARNING group.
    from exadoctor.collectors.models import CollectionResult

    rows = [
        sql_statement(1, 1, success=False, error_code="42000", error_text="object ROOT_NAME not found [line 1, column 34]"),
        sql_statement(2, 1, success=False, error_code="42000", error_text="object NOT_A_REAL_COLUMN not found [line 1, column 8]"),
    ]
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_fail(snapshot, DEFAULT_POLICY)
    assert len(findings) == 2
    assert all(f.status == FindingStatus.INFO for f in findings)


# ---- SQL-SLOW-001 -------------------------------------------------------


def test_sql_slow_not_evaluated_when_workload_unavailable():
    snapshot = make_snapshot(workload=unavailable_workload())
    findings = evaluate_sql_slow(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_sql_slow_passes_with_too_few_samples():
    from exadoctor.collectors.models import CollectionResult

    rows = [sql_statement(1, i, duration_seconds=1.0) for i in range(3)]  # below min_samples
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_slow(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_sql_slow_detects_outlier_above_median_factor():
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [sql_statement(1, i, duration_seconds=1.0) for i in range(n)]
    rows.append(sql_statement(1, n, duration_seconds=1.0 * DEFAULT_POLICY.duration_outlier_factor + 1))
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_slow(snapshot, DEFAULT_POLICY)
    assert any(f.status == FindingStatus.WARNING for f in findings)


def test_sql_slow_boundary_exactly_at_threshold_is_not_an_outlier():
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [sql_statement(1, i, duration_seconds=1.0) for i in range(n)]
    rows.append(sql_statement(1, n, duration_seconds=1.0 * DEFAULT_POLICY.duration_outlier_factor))  # == threshold, not >
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_slow(snapshot, DEFAULT_POLICY)
    assert all(f.status == FindingStatus.PASS for f in findings)


def test_sql_slow_ratio_alone_does_not_warn_on_a_trivial_absolute_difference():
    # Real bug found via live testing: 0.001s -> 0.045s clears any
    # reasonable ratio factor (45x) but is not operationally meaningful.
    # The absolute-gap floor must suppress this.
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [sql_statement(1, i, duration_seconds=0.001) for i in range(n)]
    rows.append(sql_statement(1, n, duration_seconds=0.045))
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_slow(snapshot, DEFAULT_POLICY)
    assert all(f.status == FindingStatus.PASS for f in findings)


def test_sql_slow_warns_when_both_ratio_and_absolute_gap_clear_the_floor():
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [sql_statement(1, i, duration_seconds=0.027) for i in range(n)]
    rows.append(sql_statement(1, n, duration_seconds=0.296))  # matches the real live scan example
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_slow(snapshot, DEFAULT_POLICY)
    assert any(f.status == FindingStatus.WARNING for f in findings)


def test_sql_slow_warns_when_gap_exactly_meets_the_floor_despite_float_imprecision():
    # Found by independent QA: 0.12 - 0.02 == 0.09999999999999999 in IEEE-754,
    # not 0.1, so the raw (unrounded) comparison silently failed a case that
    # should exactly clear the documented >= floor. DURATION is
    # DECIMAL(12,3), so rounding the gap to 3 places before comparing is
    # correct, not a fudge.
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [sql_statement(1, i, duration_seconds=0.02) for i in range(n)]
    rows.append(sql_statement(1, n, duration_seconds=0.12))
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_slow(snapshot, DEFAULT_POLICY)
    assert any(f.status == FindingStatus.WARNING for f in findings)


# ---- SQL-TEMP-001 -------------------------------------------------------


def test_sql_temp_not_evaluated_with_too_few_samples():
    from exadoctor.collectors.models import CollectionResult

    rows = [sql_statement(1, 1, temp_db_ram_peak_mib=10.0)]
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_temp(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_sql_temp_detects_outlier():
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [sql_statement(1, i, temp_db_ram_peak_mib=10.0) for i in range(n)]
    rows.append(sql_statement(1, n, temp_db_ram_peak_mib=10.0 * DEFAULT_POLICY.temp_outlier_factor + 1))
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_temp(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.WARNING


def test_sql_temp_ratio_alone_does_not_warn_on_a_trivial_absolute_difference():
    # Same fix as SQL-SLOW-001: a tiny median makes the ratio floor trivial
    # to clear (0.1 -> 1.0 MiB is "10x the median") without being a
    # meaningful amount of TEMP memory in absolute terms.
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [sql_statement(1, i, temp_db_ram_peak_mib=0.1) for i in range(n)]
    rows.append(sql_statement(1, n, temp_db_ram_peak_mib=1.0))
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_temp(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_sql_temp_warns_when_gap_exactly_meets_the_floor_despite_float_imprecision():
    # Same fix as SQL-SLOW-001: 9.96 - 0.01 == 9.950000000000001 in
    # IEEE-754, which rounds to the documented 10.0 MiB floor but fails a
    # raw >= comparison. TEMP_DB_RAM_PEAK is DECIMAL(10,1), so rounding the
    # gap to 1 place before comparing is correct, not a fudge.
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [sql_statement(1, i, temp_db_ram_peak_mib=0.01) for i in range(n)]
    rows.append(sql_statement(1, n, temp_db_ram_peak_mib=9.96))
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_temp(snapshot, DEFAULT_POLICY)
    assert any(f.status == FindingStatus.WARNING for f in findings)


# ---- SQL-REMOTE-001 ------------------------------------------------------


def test_sql_remote_passes_with_no_remote_reads():
    from exadoctor.collectors.models import CollectionResult

    rows = [sql_statement(1, 1, remote_read_size_mib=0.0)]
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_remote(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_sql_remote_reports_info_not_warning_when_remote_reads_present():
    from exadoctor.collectors.models import CollectionResult

    rows = [sql_statement(1, 1, remote_read_size_mib=100.0)]
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sql_remote(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.INFO  # never automatically a fault


# ---- SQL-COMMAND-SHARE-001 -------------------------------------------------


def test_command_share_not_evaluated_when_workload_unavailable():
    snapshot = make_snapshot(workload=unavailable_workload())
    findings = evaluate_command_share(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_command_share_passes_with_no_workload_activity():
    snapshot = make_snapshot()  # defaults to available, empty
    findings = evaluate_command_share(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_command_share_passes_when_spread_evenly_across_many_commands():
    from exadoctor.collectors.models import CollectionResult

    # 10 distinct command types, one statement each, identical duration/CPU
    # -- each is exactly 10% of the total, comfortably under both default
    # thresholds only because there are enough distinct types to dilute any
    # one of them... actually 10% would clear a 0.5%/1.0% threshold, so use
    # enough distinct types that no single one reaches either bar.
    rows = [
        sql_statement(1, i, command_name=f"CMD_{i}", duration_seconds=1.0, cpu_percent=1.0)
        for i in range(300)
    ]
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_command_share(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_command_share_reports_dominant_command_by_duration():
    from exadoctor.collectors.models import CollectionResult

    rows = [sql_statement(1, 1, command_name="SELECT", duration_seconds=99.0, cpu_percent=1.0)]
    rows += [sql_statement(1, i, command_name="COMMIT", duration_seconds=0.01, cpu_percent=1.0) for i in range(2, 5)]
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_command_share(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.INFO
    assert "SELECT" in findings[0].summary


def test_command_share_reports_command_that_clears_only_the_cpu_threshold():
    from exadoctor.collectors.models import CollectionResult

    # ROLLBACK: tiny duration share but pegs CPU the whole time it runs --
    # clears the CPU threshold (>=1.0%) while its duration share stays far
    # below the 0.5% duration threshold, exercising the OR (not AND) logic.
    rows = [sql_statement(1, 1, command_name="ROLLBACK", duration_seconds=0.001, cpu_percent=100.0)]
    rows += [sql_statement(1, i, command_name="SELECT", duration_seconds=100.0, cpu_percent=0.0) for i in range(2, 5)]
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_command_share(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.INFO
    assert "ROLLBACK" in findings[0].summary


def test_command_share_cpu_seconds_not_a_naive_percentage_sum():
    from exadoctor.collectors.models import CollectionResult

    # Two SELECTs at 50% CPU for 10s each = 10 CPU-seconds combined (5+5),
    # not "100%" from naively summing the raw percentages -- this is the
    # correctness fix over the legacy tool's own approach.
    rows = [sql_statement(1, i, command_name="SELECT", duration_seconds=10.0, cpu_percent=50.0) for i in (1, 2)]
    snapshot = make_snapshot(workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_command_share(snapshot, DEFAULT_POLICY)
    # 2 statements * 50% CPU * 10s = 10.0 CPU-seconds total, not 100.0
    # (which a naive sum of the raw CPU% values would have produced).
    assert "10.0 total CPU-seconds" in findings[0].evidence[0].context


# ---- SQL-CONFLICT-001 -----------------------------------------------------


def test_transaction_conflicts_not_evaluated_when_unavailable():
    snapshot = make_snapshot(transaction_conflicts=unavailable_transaction_conflicts())
    findings = evaluate_transaction_conflicts(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_transaction_conflicts_passes_with_no_conflicts():
    snapshot = make_snapshot()  # defaults to available, empty
    findings = evaluate_transaction_conflicts(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_transaction_conflicts_info_when_workload_duration_unavailable():
    from exadoctor.collectors.models import CollectionResult

    rows = [transaction_conflict(DB_TIME)]
    snapshot = make_snapshot(
        transaction_conflicts=CollectionResult("EXA_DBA_TRANSACTION_CONFLICTS", "PUBLIC", True, None, rows),
        workload=unavailable_workload(),
    )
    findings = evaluate_transaction_conflicts(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.INFO


def test_transaction_conflicts_pass_when_share_below_threshold():
    from exadoctor.collectors.models import CollectionResult

    # 1 second of conflict wait against a 10,000-second total workload is
    # 0.01% -- well under the 1.0% default threshold.
    rows = [transaction_conflict(DB_TIME)]
    workload_rows = [sql_statement(1, 1, duration_seconds=10000.0)]
    snapshot = make_snapshot(
        transaction_conflicts=CollectionResult("EXA_DBA_TRANSACTION_CONFLICTS", "PUBLIC", True, None, rows),
        workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, workload_rows),
    )
    findings = evaluate_transaction_conflicts(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_transaction_conflicts_warns_when_share_at_or_above_threshold():
    from datetime import timedelta

    from exadoctor.collectors.models import CollectionResult

    # 100 seconds of conflict wait against a 1000-second total workload is
    # 10% -- clears the 1.0% default threshold.
    rows = [transaction_conflict(DB_TIME, stop_time=DB_TIME + timedelta(seconds=100))]
    workload_rows = [sql_statement(1, 1, duration_seconds=1000.0)]
    snapshot = make_snapshot(
        transaction_conflicts=CollectionResult("EXA_DBA_TRANSACTION_CONFLICTS", "PUBLIC", True, None, rows),
        workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, workload_rows),
    )
    findings = evaluate_transaction_conflicts(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.WARNING
    assert "SCHEMA.TABLE" in findings[0].summary  # the default transaction_conflict() object


def test_transaction_conflicts_excludes_still_open_conflicts_from_duration():
    from exadoctor.collectors.models import CollectionResult

    # An open conflict (no stop_time) must not crash the duration sum and
    # must not silently count as zero-duration -- it's excluded and called
    # out via the open-conflict limitation instead.
    rows = [
        transaction_conflict(DB_TIME, stop_time=None),
        transaction_conflict(DB_TIME),
    ]
    workload_rows = [sql_statement(1, 1, duration_seconds=100.0)]
    snapshot = make_snapshot(
        transaction_conflicts=CollectionResult("EXA_DBA_TRANSACTION_CONFLICTS", "PUBLIC", True, None, rows),
        workload=CollectionResult("EXA_SQL_LAST_DAY", "PUBLIC", True, None, workload_rows),
    )
    findings = evaluate_transaction_conflicts(snapshot, DEFAULT_POLICY)
    assert any("still open" in lim or "1 conflict" in lim for lim in findings[0].limitations)


# ---- SYS-TEMP-001 --------------------------------------------------------


def test_sys_temp_not_evaluated_with_too_few_samples():
    from exadoctor.collectors.models import CollectionResult

    rows = [monitor_sample(DB_TIME, temp_db_ram_mib=10.0)]
    snapshot = make_snapshot(monitoring=CollectionResult("EXA_MONITOR_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sys_temp(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_sys_temp_detects_spike():
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [monitor_sample(DB_TIME, temp_db_ram_mib=10.0) for _ in range(n)]
    rows.append(monitor_sample(DB_TIME, temp_db_ram_mib=10.0 * DEFAULT_POLICY.monitor_spike_factor + 1))
    snapshot = make_snapshot(monitoring=CollectionResult("EXA_MONITOR_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sys_temp(snapshot, DEFAULT_POLICY)
    assert any(f.status == FindingStatus.WARNING and "spike" in f.title.lower() for f in findings)


def test_sys_temp_detects_sustained_elevation():
    from exadoctor.collectors.models import CollectionResult

    # A 50/50 low/high split shifts the median itself (statistics.median
    # averages the two middle values for an even-length list), so the ratio
    # between low and high must be large enough that the high half still
    # clears persistence_factor times that shifted median. With low=1,
    # high=20: median=(1+20)/2=10.5, threshold=10.5*1.5=15.75 < 20 -- clears it.
    n = 10
    rows = [monitor_sample(DB_TIME, temp_db_ram_mib=1.0) for _ in range(n // 2)]
    rows += [monitor_sample(DB_TIME, temp_db_ram_mib=20.0) for _ in range(n // 2)]
    snapshot = make_snapshot(monitoring=CollectionResult("EXA_MONITOR_LAST_DAY", "PUBLIC", True, None, rows))
    findings = evaluate_sys_temp(snapshot, DEFAULT_POLICY)
    assert any("sustained" in f.title.lower() for f in findings)


# ---- SYS-RESOURCE-TREND-001 ------------------------------------------------


def test_resource_trend_not_evaluated_when_unavailable():
    snapshot = make_snapshot(monitor_daily=unavailable_monitor_daily())
    findings = evaluate_resource_trend(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_resource_trend_not_evaluated_with_too_few_days():
    from exadoctor.collectors.models import CollectionResult

    rows = [monitor_daily_sample(DB_TIME - timedelta(days=i)) for i in range(2)]
    snapshot = make_snapshot(monitor_daily=CollectionResult("EXA_MONITOR_DAILY", "PUBLIC", True, None, rows))
    findings = evaluate_resource_trend(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_resource_trend_passes_when_flat():
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [
        monitor_daily_sample(
            DB_TIME - timedelta(days=n - i), cpu_avg_percent=10.0, temp_db_ram_avg_mib=100.0,
            net_avg_mib_per_sec=2.0, swap_avg_mib_per_sec=0.0,
        )
        for i in range(n)
    ]
    snapshot = make_snapshot(monitor_daily=CollectionResult("EXA_MONITOR_DAILY", "PUBLIC", True, None, rows))
    findings = evaluate_resource_trend(snapshot, DEFAULT_POLICY)
    assert all(f.status == FindingStatus.PASS for f in findings)


def test_resource_trend_warns_on_cpu_growth():
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [monitor_daily_sample(DB_TIME - timedelta(days=n - i), cpu_avg_percent=1.0) for i in range(n - 1)]
    rows.append(
        monitor_daily_sample(DB_TIME, cpu_avg_percent=1.0 * DEFAULT_POLICY.resource_trend_growth_factor + 10)
    )
    snapshot = make_snapshot(monitor_daily=CollectionResult("EXA_MONITOR_DAILY", "PUBLIC", True, None, rows))
    findings = evaluate_resource_trend(snapshot, DEFAULT_POLICY)
    assert any(f.status == FindingStatus.WARNING and "CPU" in f.title for f in findings)


def test_resource_trend_warns_on_swap_emerging_from_zero_baseline():
    from exadoctor.collectors.models import CollectionResult

    # SWAP has no meaningful "ratio off zero" -- the absolute floor alone
    # must decide when the trailing median is exactly 0, which is the
    # normal/healthy baseline for swap.
    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [monitor_daily_sample(DB_TIME - timedelta(days=n - i), swap_avg_mib_per_sec=0.0) for i in range(n - 1)]
    rows.append(
        monitor_daily_sample(DB_TIME, swap_avg_mib_per_sec=DEFAULT_POLICY.resource_trend_min_absolute_swap_mib_per_sec)
    )
    snapshot = make_snapshot(monitor_daily=CollectionResult("EXA_MONITOR_DAILY", "PUBLIC", True, None, rows))
    findings = evaluate_resource_trend(snapshot, DEFAULT_POLICY)
    assert any(f.status == FindingStatus.WARNING and "swap" in f.title.lower() for f in findings)


def test_resource_trend_ratio_alone_does_not_warn_on_a_trivial_absolute_difference():
    from exadoctor.collectors.models import CollectionResult

    # 10x the median (0.001 -> 0.01) but the absolute gap is nowhere near
    # the CPU floor -- same lesson SQL-SLOW-001/SQL-TEMP-001 already learned.
    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [monitor_daily_sample(DB_TIME - timedelta(days=n - i), cpu_avg_percent=0.001) for i in range(n - 1)]
    rows.append(monitor_daily_sample(DB_TIME, cpu_avg_percent=0.01))
    snapshot = make_snapshot(monitor_daily=CollectionResult("EXA_MONITOR_DAILY", "PUBLIC", True, None, rows))
    findings = evaluate_resource_trend(snapshot, DEFAULT_POLICY)
    assert all(f.status == FindingStatus.PASS for f in findings)


def test_resource_trend_reports_multiple_metrics_independently():
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [
        monitor_daily_sample(DB_TIME - timedelta(days=n - i), cpu_avg_percent=1.0, net_avg_mib_per_sec=1.0)
        for i in range(n - 1)
    ]
    rows.append(
        monitor_daily_sample(
            DB_TIME,
            cpu_avg_percent=1.0 * DEFAULT_POLICY.resource_trend_growth_factor + 10,
            net_avg_mib_per_sec=1.0 * DEFAULT_POLICY.resource_trend_growth_factor + 10,
        )
    )
    snapshot = make_snapshot(monitor_daily=CollectionResult("EXA_MONITOR_DAILY", "PUBLIC", True, None, rows))
    findings = evaluate_resource_trend(snapshot, DEFAULT_POLICY)
    warnings = [f for f in findings if f.status == FindingStatus.WARNING]
    assert len(warnings) == 2


def test_resource_trend_compares_against_latest_day_not_an_older_spike():
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [monitor_daily_sample(DB_TIME - timedelta(days=n - i), cpu_avg_percent=1.0) for i in range(n - 1)]
    rows[1] = monitor_daily_sample(rows[1].interval_start, cpu_avg_percent=100.0)  # an old spike, not the latest day
    rows.append(monitor_daily_sample(DB_TIME, cpu_avg_percent=1.0))  # latest day is normal
    snapshot = make_snapshot(monitor_daily=CollectionResult("EXA_MONITOR_DAILY", "PUBLIC", True, None, rows))
    findings = evaluate_resource_trend(snapshot, DEFAULT_POLICY)
    assert all(f.status == FindingStatus.PASS for f in findings)


# ---- STORAGE-GROWTH-001 ---------------------------------------------------


def test_storage_growth_not_evaluated_when_unavailable():
    snapshot = make_snapshot(storage=unavailable_storage())
    findings = evaluate_storage_growth(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_storage_growth_not_evaluated_with_too_few_days():
    from exadoctor.collectors.models import CollectionResult

    rows = [db_size_sample(DB_TIME - timedelta(days=i)) for i in range(2)]
    snapshot = make_snapshot(storage=CollectionResult("EXA_DB_SIZE_DAILY", "PUBLIC", True, None, rows))
    findings = evaluate_storage_growth(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_storage_growth_passes_within_trend():
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [db_size_sample(DB_TIME - timedelta(days=n - i), storage_size_avg_gib=10.0) for i in range(n)]
    snapshot = make_snapshot(storage=CollectionResult("EXA_DB_SIZE_DAILY", "PUBLIC", True, None, rows))
    findings = evaluate_storage_growth(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_storage_growth_warns_on_unusual_growth():
    from exadoctor.collectors.models import CollectionResult

    n = DEFAULT_POLICY.min_samples_for_class_statistics
    rows = [db_size_sample(DB_TIME - timedelta(days=n - i), storage_size_avg_gib=10.0) for i in range(n - 1)]
    rows.append(db_size_sample(DB_TIME, storage_size_avg_gib=10.0 * DEFAULT_POLICY.storage_growth_factor + 1))
    snapshot = make_snapshot(storage=CollectionResult("EXA_DB_SIZE_DAILY", "PUBLIC", True, None, rows))
    findings = evaluate_storage_growth(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.WARNING


# ---- SYS-RAM-SIZING-001 ---------------------------------------------------


def test_ram_sizing_not_evaluated_when_storage_unavailable():
    snapshot = make_snapshot(storage=unavailable_storage())
    findings = evaluate_ram_sizing(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_ram_sizing_not_evaluated_when_no_row_has_the_value():
    from exadoctor.collectors.models import CollectionResult

    rows = [db_size_sample(DB_TIME, recommended_db_ram_size_avg_gib=None)]
    snapshot = make_snapshot(storage=CollectionResult("EXA_DB_SIZE_DAILY", "PUBLIC", True, None, rows))
    findings = evaluate_ram_sizing(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_ram_sizing_reports_the_latest_recommendation_as_info_when_no_actual_ram_known():
    # EXA_SYSTEM_EVENTS defaults to empty (available, no rows) in make_snapshot
    # -- this is the "can't compare, fall back to reporting the recommendation
    # alone" path, same as this rule's original (pre-EXA_SYSTEM_EVENTS) behavior.
    from exadoctor.collectors.models import CollectionResult

    rows = [
        db_size_sample(DB_TIME - timedelta(days=1), recommended_db_ram_size_avg_gib=100.0),
        db_size_sample(DB_TIME, recommended_db_ram_size_avg_gib=250.0),
    ]
    snapshot = make_snapshot(storage=CollectionResult("EXA_DB_SIZE_DAILY", "PUBLIC", True, None, rows))
    findings = evaluate_ram_sizing(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.INFO
    # Must report the *latest* row's value (250.0), not the first one (100.0).
    assert findings[0].evidence[0].value == 250.0
    assert "250.0 GiB" in findings[0].summary


def test_ram_sizing_reports_info_when_system_events_explicitly_unavailable():
    from exadoctor.collectors.models import CollectionResult

    rows = [db_size_sample(DB_TIME, recommended_db_ram_size_avg_gib=250.0)]
    snapshot = make_snapshot(
        storage=CollectionResult("EXA_DB_SIZE_DAILY", "PUBLIC", True, None, rows),
        system_events=unavailable_system_events(),
    )
    findings = evaluate_ram_sizing(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.INFO


def test_ram_sizing_warns_when_actual_ram_is_below_the_recommendation():
    from exadoctor.collectors.models import CollectionResult

    rows = [db_size_sample(DB_TIME, recommended_db_ram_size_avg_gib=250.0)]
    events = [system_event(DB_TIME, db_ram_size_gib=100.0)]
    snapshot = make_snapshot(
        storage=CollectionResult("EXA_DB_SIZE_DAILY", "PUBLIC", True, None, rows),
        system_events=CollectionResult("EXA_SYSTEM_EVENTS", "PUBLIC", True, None, events),
    )
    findings = evaluate_ram_sizing(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.WARNING
    assert "100.0 GiB" in findings[0].summary
    assert "250.0 GiB" in findings[0].summary


def test_ram_sizing_passes_when_actual_ram_meets_the_recommendation():
    from exadoctor.collectors.models import CollectionResult

    rows = [db_size_sample(DB_TIME, recommended_db_ram_size_avg_gib=100.0)]
    events = [system_event(DB_TIME, db_ram_size_gib=250.0)]
    snapshot = make_snapshot(
        storage=CollectionResult("EXA_DB_SIZE_DAILY", "PUBLIC", True, None, rows),
        system_events=CollectionResult("EXA_SYSTEM_EVENTS", "PUBLIC", True, None, events),
    )
    findings = evaluate_ram_sizing(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_ram_sizing_uses_the_most_recent_system_event_not_an_earlier_one():
    from exadoctor.collectors.models import CollectionResult

    rows = [db_size_sample(DB_TIME, recommended_db_ram_size_avg_gib=50.0)]
    events = [
        system_event(DB_TIME - timedelta(days=30), db_ram_size_gib=10.0),  # older, would WARN
        system_event(DB_TIME, db_ram_size_gib=100.0),  # latest, actually provisioned now
    ]
    snapshot = make_snapshot(
        storage=CollectionResult("EXA_DB_SIZE_DAILY", "PUBLIC", True, None, rows),
        system_events=CollectionResult("EXA_SYSTEM_EVENTS", "PUBLIC", True, None, events),
    )
    findings = evaluate_ram_sizing(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS
    assert findings[0].evidence[0].value == 100.0


# ---- SESSION-LONG-001 -----------------------------------------------------


def test_session_long_not_evaluated_when_sessions_unavailable():
    snapshot = make_snapshot(sessions=unavailable_sessions())
    findings = evaluate_session_long(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_session_long_not_evaluated_without_database_time():
    from exadoctor.collectors.models import CollectionResult

    rows = [session_info(1, login_time=DB_TIME - timedelta(hours=2))]
    snapshot = make_snapshot(
        sessions=CollectionResult("EXA_ALL_SESSIONS", "PUBLIC", True, None, rows), database_time=None
    )
    findings = evaluate_session_long(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_session_long_passes_for_short_sessions():
    from exadoctor.collectors.models import CollectionResult

    rows = [session_info(1, login_time=DB_TIME - timedelta(minutes=5))]
    snapshot = make_snapshot(sessions=CollectionResult("EXA_ALL_SESSIONS", "PUBLIC", True, None, rows))
    findings = evaluate_session_long(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_session_long_flags_session_past_threshold():
    from exadoctor.collectors.models import CollectionResult

    threshold_hours = DEFAULT_POLICY.long_session_threshold_seconds / 3600
    rows = [session_info(42, login_time=DB_TIME - timedelta(hours=threshold_hours + 1))]
    snapshot = make_snapshot(sessions=CollectionResult("EXA_ALL_SESSIONS", "PUBLIC", True, None, rows))
    findings = evaluate_session_long(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.INFO
    assert findings[0].evidence[0].session_id == 42


def test_session_long_boundary_exactly_at_threshold_is_flagged():
    from exadoctor.collectors.models import CollectionResult

    rows = [session_info(1, login_time=DB_TIME - timedelta(seconds=DEFAULT_POLICY.long_session_threshold_seconds))]
    snapshot = make_snapshot(sessions=CollectionResult("EXA_ALL_SESSIONS", "PUBLIC", True, None, rows))
    findings = evaluate_session_long(snapshot, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.INFO  # >= threshold, so exactly-at counts
