from exadoctor.models.finding import FindingStatus
from exadoctor.profile.models import QueryProfile, QueryProfilePart
from exadoctor.profile.rules import (
    evaluate_bottleneck,
    evaluate_expression_index,
    evaluate_global_operation,
    evaluate_query_profile,
    evaluate_temp_materialization,
)
from exadoctor.rules.policy import DEFAULT_POLICY


def _part(part_id: int, **kwargs) -> QueryProfilePart:
    defaults = dict(
        part_id=part_id,
        part_name="SCAN",
        part_info=None,
        object_schema=None,
        object_name=None,
        object_rows=None,
        in_rows=None,
        out_rows=None,
        duration=None,
        cpu=None,
        temp_db_ram_peak=None,
        mem_peak=None,
        local_read_size=None,
        remote_read_size=None,
        network=None,
        process_id=None,
        node_id=None,
        start_time=None,
        stop_time=None,
        remarks=None,
    )
    defaults.update(kwargs)
    return QueryProfilePart(**defaults)


# ---- PERF-BOTTLENECK-001 --------------------------------------------------


def test_bottleneck_not_evaluated_with_no_parts():
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[])
    findings = evaluate_bottleneck(profile, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.NOT_EVALUATED


def test_bottleneck_info_when_below_share_threshold():
    parts = [_part(1, duration=1.0), _part(2, duration=1.0), _part(3, duration=1.0)]
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=parts)
    findings = evaluate_bottleneck(profile, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.INFO


def test_bottleneck_passes_when_total_duration_is_exactly_zero():
    # A real bug caught via live testing: a genuinely fast statement whose
    # DURATION rounds to 0.000 is real data, not missing evidence -- it
    # must not be reported as NOT_EVALUATED.
    parts = [_part(1, duration=0.0), _part(2, duration=0.0)]
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=parts)
    findings = evaluate_bottleneck(profile, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS
    assert "0.000s" in findings[0].summary


def test_bottleneck_warning_when_one_part_dominates():
    parts = [_part(1, duration=9.0), _part(2, duration=1.0)]
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=parts)
    findings = evaluate_bottleneck(profile, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.WARNING
    assert findings[0].evidence[0].part_id == 1


# ---- PERF-GLOBAL-001 -------------------------------------------------------


def test_global_operation_passes_with_no_global_parts():
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[_part(1, part_info=None)])
    findings = evaluate_global_operation(profile, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_global_operation_reports_info_for_each_global_part():
    parts = [_part(1, part_info="GLOBAL", network=5.0), _part(2, part_info="GLOBAL, REPLICATED")]
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=parts)
    findings = evaluate_global_operation(profile, DEFAULT_POLICY)
    assert len(findings) == 2
    assert all(f.status == FindingStatus.INFO for f in findings)


# ---- PERF-EXPR-INDEX-001 ---------------------------------------------------


def test_expression_index_passes_when_absent():
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[_part(1, part_info=None)])
    findings = evaluate_expression_index(profile, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_expression_index_warns_when_present():
    part = _part(1, part_info="EXPRESSION INDEX", object_schema="S", object_name="T", duration=2.0)
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[part, _part(2, duration=1.0)])
    findings = evaluate_expression_index(profile, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.WARNING
    assert "S.T" in findings[0].summary


# ---- PERF-TEMP-MATERIALIZE-001 --------------------------------------------


def test_temp_materialize_passes_with_no_temp_usage():
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[_part(1, temp_db_ram_peak=0.0)])
    findings = evaluate_temp_materialization(profile, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.PASS


def test_temp_materialize_info_below_threshold_and_not_marked_temporary():
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[_part(1, temp_db_ram_peak=1.0, part_info=None)])
    findings = evaluate_temp_materialization(profile, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.INFO


def test_temp_materialize_warns_above_threshold():
    peak = DEFAULT_POLICY.temp_materialize_mib_threshold + 1
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[_part(1, temp_db_ram_peak=peak, out_rows=100)])
    findings = evaluate_temp_materialization(profile, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.WARNING


def test_temp_materialize_warns_when_marked_temporary_even_below_threshold():
    profile = QueryProfile(
        1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[_part(1, temp_db_ram_peak=1.0, part_info="TEMPORARY")]
    )
    findings = evaluate_temp_materialization(profile, DEFAULT_POLICY)
    assert findings[0].status == FindingStatus.WARNING


# ---- evaluate_query_profile orchestration ----------------------------------


def test_evaluate_query_profile_runs_all_rules_independently():
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[_part(1, duration=1.0)])
    findings = evaluate_query_profile(profile, DEFAULT_POLICY)
    ids = {f.id for f in findings}
    assert {"PERF-BOTTLENECK-001", "PERF-GLOBAL-001", "PERF-EXPR-INDEX-001", "PERF-TEMP-MATERIALIZE-001"} <= ids
