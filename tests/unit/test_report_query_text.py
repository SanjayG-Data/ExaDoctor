"""Direct tests for the `exadoctor query` text renderer.

This module had ZERO test coverage before these tests were added --
neither a unit test nor a live run had ever exercised the "profile has
parts" branch (the aligned parts table), since the available test
instance has profiling broadly disabled. A rarely-exercised
success path going untested for a while is exactly how `render_scan_text`
picked up a real regression once (a rename left it calling a helper that
no longer existed, undetected because nothing directly tested it). These
tests close that same kind of gap here without needing live multi-part
profile data.
"""

from __future__ import annotations

from datetime import datetime

from exadoctor.collectors.models import SqlStatement
from exadoctor.models.finding import Evidence, Finding, FindingStatus
from exadoctor.profile.analyzer import QueryAnalysis
from exadoctor.profile.models import QueryProfile, QueryProfilePart
from exadoctor.report.query_text import render_query_text


def _workload() -> SqlStatement:
    return SqlStatement(
        session_id=42,
        stmt_id=7,
        command_name="SELECT",
        command_class="DQL",
        duration_seconds=0.296,
        start_time=datetime(2026, 8, 22, 12, 0, 0),
        stop_time=datetime(2026, 8, 22, 12, 0, 1),
        cpu_percent=12.0,
        temp_db_ram_peak_mib=5.2,
        local_read_size_mib=1.0,
        remote_read_size_mib=0.0,
        net_mib_per_sec=0.0,
        success=True,
        error_code=None,
        error_text=None,
        row_count=42,
        cluster_name="MAIN",
    )


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


def _finding() -> Finding:
    return Finding(
        id="PERF-BOTTLENECK-001",
        title="Dominant execution part",
        category="query",
        status=FindingStatus.INFO,
        summary="Part #1 dominates.",
    )


def test_render_query_text_when_neither_workload_nor_profile_available() -> None:
    analysis = QueryAnalysis(
        session_id=1, stmt_id=1, workload=None, workload_available=False,
        profile=None, profile_available=False, findings=[_finding()],
    )
    text = render_query_text(analysis)

    assert "EXADOCTOR QUERY ANALYSIS" in text
    assert "Session: 1" in text and "Statement: 1" in text
    assert "Not available: no EXA_SQL_LAST_DAY row" in text
    assert "Not available: no rows in EXA_DBA_PROFILE_LAST_DAY" in text


def test_render_query_text_renders_workload_summary() -> None:
    analysis = QueryAnalysis(
        session_id=42, stmt_id=7, workload=_workload(), workload_available=True,
        profile=None, profile_available=False, findings=[],
    )
    text = render_query_text(analysis)

    assert "Command: SELECT (DQL)" in text
    assert "Duration: 0.296s" in text
    assert "CPU: 12.0%" in text
    assert "TEMP peak: 5.2 MiB" in text
    assert "Rows: 42" in text


def test_render_query_text_renders_workload_error() -> None:
    failed = _workload()
    failed.success = False
    failed.error_code = "42000"
    failed.error_text = "object X not found"
    analysis = QueryAnalysis(
        session_id=1, stmt_id=1, workload=failed, workload_available=True,
        profile=None, profile_available=False, findings=[],
    )
    text = render_query_text(analysis)
    assert "Error: 42000 object X not found" in text


def test_render_query_text_renders_the_profile_parts_table() -> None:
    # The exact branch that had never run anywhere in this project's history.
    profile = QueryProfile(
        session_id=42,
        stmt_id=7,
        source="EXA_DBA_PROFILE_LAST_DAY",
        parts=[
            _part(1, part_name="SCAN", duration=0.1, cpu=4.0, temp_db_ram_peak=1.0, out_rows=1000, part_info=None),
            _part(2, part_name="JOIN", duration=0.196, cpu=8.0, temp_db_ram_peak=4.2, out_rows=50, part_info="GLOBAL"),
        ],
    )
    analysis = QueryAnalysis(
        session_id=42, stmt_id=7, workload=_workload(), workload_available=True,
        profile=profile, profile_available=True, findings=[_finding()],
    )
    text = render_query_text(analysis)

    assert "PROFILE (EXA_DBA_PROFILE_LAST_DAY)" in text
    assert "SCAN" in text and "JOIN" in text
    assert "GLOBAL" in text
    assert "Total profiled duration: 0.296s across 2 part(s)" in text
    # column values must actually appear formatted, not raise/produce garbage
    assert "0.100" in text
    assert "0.196" in text


def test_render_query_text_part_name_column_widens_for_long_names() -> None:
    # PART_NAME is VARCHAR(40) in Exasol -- a fixed-width column (the same
    # bug class exadoctor.baseline.history found and fixed for its own
    # table) must not misalign for a name longer than a guessed default.
    long_name = "A" * 35
    profile = QueryProfile(
        session_id=1, stmt_id=1, source="EXA_DBA_PROFILE_LAST_DAY",
        parts=[_part(1, part_name=long_name, duration=0.1)],
    )
    analysis = QueryAnalysis(
        session_id=1, stmt_id=1, workload=None, workload_available=False,
        profile=profile, profile_available=True, findings=[],
    )
    text = render_query_text(analysis)

    # the header's "DURATION" label must not be glued directly onto the
    # long part name with zero separation.
    for line in text.splitlines():
        if long_name in line:
            assert long_name + "DURATION" not in line
            break
    else:
        raise AssertionError("expected the long part name to appear in the rendered table")


def test_render_query_text_includes_ai_explanation_when_given() -> None:
    analysis = QueryAnalysis(
        session_id=1, stmt_id=1, workload=None, workload_available=False,
        profile=None, profile_available=False, findings=[],
    )
    text = render_query_text(analysis, ai_explanation="This query looks fine.")
    assert "AI EXPLANATION" in text
    assert "This query looks fine." in text


def test_render_query_text_never_shows_a_self_referential_drill_down_hint() -> None:
    """render_findings_block's drill-down hint (added for `exadoctor scan`,
    where it points a reader at a *different* command to run) is
    suppressed here -- every finding in a query report is already about
    the one session/statement named in this report's own header, so the
    hint would just echo the command the reader already ran. Found and
    fixed as a direct side effect of adding that hint to the scan report."""
    finding_with_matching_evidence = Finding(
        id="PERF-BOTTLENECK-001",
        title="Dominant execution part",
        category="query",
        status=FindingStatus.WARNING,
        summary="Part #1 dominates.",
        evidence=[
            Evidence(
                source="EXA_DBA_PROFILE_LAST_DAY",
                stability="PUBLIC",
                metric="DURATION",
                value=0.1,
                unit="seconds",
                timestamp=None,
                session_id=42,
                stmt_id=7,
            )
        ],
    )
    analysis = QueryAnalysis(
        session_id=42, stmt_id=7, workload=None, workload_available=False,
        profile=None, profile_available=False, findings=[finding_with_matching_evidence],
    )
    text = render_query_text(analysis)
    assert "exadoctor query" not in text


def test_render_query_text_omits_ai_section_when_not_given() -> None:
    analysis = QueryAnalysis(
        session_id=1, stmt_id=1, workload=None, workload_available=False,
        profile=None, profile_available=False, findings=[],
    )
    text = render_query_text(analysis)
    assert "AI EXPLANATION" not in text
