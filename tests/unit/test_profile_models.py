import json

from exadoctor.profile.models import QueryProfile, QueryProfilePart


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


def test_total_duration_sums_timed_parts():
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[_part(1, duration=1.0), _part(2, duration=2.5)])
    assert profile.total_duration() == 3.5


def test_total_duration_none_when_no_parts_timed():
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[_part(1, duration=None)])
    assert profile.total_duration() is None


def test_dominant_part_is_the_longest():
    p1, p2 = _part(1, duration=1.0), _part(2, duration=5.0)
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[p1, p2])
    assert profile.dominant_part() is p2


def test_duration_share_computes_fraction():
    p1, p2 = _part(1, duration=1.0), _part(2, duration=3.0)
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[p1, p2])
    assert profile.duration_share(p2) == 0.75


def test_marker_filters_use_exasol_documented_part_info_vocabulary():
    global_part = _part(1, part_info="GLOBAL")
    expr_part = _part(2, part_info="EXPRESSION INDEX")
    temp_part = _part(3, part_info="TEMPORARY")
    plain_part = _part(4, part_info=None)
    profile = QueryProfile(1, 1, "EXA_DBA_PROFILE_LAST_DAY", parts=[global_part, expr_part, temp_part, plain_part])

    assert profile.global_parts() == [global_part]
    assert profile.expression_index_parts() == [expr_part]
    assert profile.temporary_parts() == [temp_part]


def test_query_profile_round_trips_through_json():
    profile = QueryProfile(
        session_id=42,
        stmt_id=7,
        source="EXA_DBA_PROFILE_LAST_DAY",
        parts=[_part(1, part_name="ROLLBACK", duration=0.002, cpu=4.5)],
    )
    restored = QueryProfile.from_dict(json.loads(json.dumps(profile.to_dict())))
    assert restored == profile
