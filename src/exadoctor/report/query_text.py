"""Terminal renderer for `exadoctor query` (roadmap Milestone 9)."""

from __future__ import annotations

from exadoctor.profile.analyzer import QueryAnalysis, SessionStatementList
from exadoctor.report.terminal import render_ai_explanation_block, render_findings_block

# A genuinely long-lived or pooled session can run hundreds/thousands of
# statements in EXA_SQL_LAST_DAY's 24h window -- confirmed live (80 rows
# for one moderately active local session). Same "cap, and say so" policy
# this project already applies elsewhere (e.g. RulePolicy.
# max_findings_per_rule) rather than dumping an unusably long terminal
# listing. This caps only the text *display*; --format json always
# returns every statement.
MAX_STATEMENTS_SHOWN = 50


def render_session_statements_text(result: SessionStatementList) -> str:
    """Renders `exadoctor query SESSION_ID` (STMT_ID omitted) -- a listing
    to help a user who only has a session_id (e.g. from SESSION-LONG-001,
    which never carries a stmt_id) pick a statement worth a deep look."""
    lines = ["EXADOCTOR SESSION STATEMENTS", "", f"Session: {result.session_id}", ""]

    if not result.available:
        lines.append(f"Not available: {result.reason or 'EXA_SQL_LAST_DAY unavailable'}.")
        return "\n".join(lines).rstrip() + "\n"

    if not result.statements:
        lines.append("No statements found for this session in EXA_SQL_LAST_DAY's 24-hour window.")
        return "\n".join(lines).rstrip() + "\n"

    total = len(result.statements)
    # Statements are already sorted ascending by START_TIME (see
    # list_session_statements) -- the tail is the most recent activity,
    # generally the most relevant slice to show when truncating.
    shown = result.statements[-MAX_STATEMENTS_SHOWN:] if total > MAX_STATEMENTS_SHOWN else result.statements

    lines.append(f"{total} statement(s) found -- pick a STMT_ID and re-run with it:")
    if len(shown) < total:
        lines.append(f"(showing the {len(shown)} most recent; {total - len(shown)} older not shown -- use --format json for the complete list)")
    lines.append("")
    lines.append(f"  {'STMT_ID':<9}{'COMMAND':<14}{'SUCCESS':<9}{'DURATION':>10}  START_TIME")
    for s in shown:
        duration = f"{s.duration_seconds:.3f}s" if s.duration_seconds is not None else "-"
        start = s.start_time.isoformat() if s.start_time else "-"
        lines.append(f"  {s.stmt_id:<9}{s.command_name:<14}{str(s.success):<9}{duration:>10}  {start}")
    lines.append("")
    lines.append(f"Drill into one: exadoctor query {result.session_id} <STMT_ID>")

    return "\n".join(lines).rstrip() + "\n"


def render_query_text(analysis: QueryAnalysis, ai_explanation: str | None = None) -> str:
    lines = ["EXADOCTOR QUERY ANALYSIS", ""]
    lines.append(f"Session: {analysis.session_id}   Statement: {analysis.stmt_id}")
    lines.append("")

    lines.append("WORKLOAD (EXA_SQL_LAST_DAY)")
    if analysis.workload is None:
        lines.append("  Not available: no EXA_SQL_LAST_DAY row found for this session/statement.")
    else:
        w = analysis.workload
        lines.append(f"  Command: {w.command_name} ({w.command_class})   Success: {w.success}")
        duration = f"{w.duration_seconds:.3f}s" if w.duration_seconds is not None else "unknown"
        cpu = f"{w.cpu_percent:.1f}%" if w.cpu_percent is not None else "unknown"
        lines.append(f"  Duration: {duration}   CPU: {cpu}")
        temp = f"{w.temp_db_ram_peak_mib:.1f} MiB" if w.temp_db_ram_peak_mib is not None else "unknown"
        remote = f"{w.remote_read_size_mib:.1f} MiB" if w.remote_read_size_mib is not None else "unknown"
        lines.append(f"  TEMP peak: {temp}   Remote read: {remote}   Rows: {w.row_count}")
        if w.start_time:
            lines.append(f"  Started: {w.start_time.isoformat()}")
        if not w.success and w.error_text:
            lines.append(f"  Error: {w.error_code} {w.error_text}")
    lines.append("")

    lines.append(f"PROFILE ({analysis.profile.source if analysis.profile else 'not available'})")
    if analysis.profile is None:
        lines.append("  Not available: no rows in EXA_DBA_PROFILE_LAST_DAY or EXA_DBA_PROFILE_RUNNING.")
    else:
        # PART_NAME is VARCHAR(40) in Exasol; a fixed-width column (same bug
        # class exadoctor.baseline.history found and fixed for its own
        # table) would misalign for any name longer than the assumed width.
        # Size the column to the actual longest name in this profile instead.
        name_width = max((len(p.part_name) for p in analysis.profile.parts), default=4) + 2
        header = f"  {'#':<4}{'PART':<{name_width}}{'DURATION':>10}{'CPU%':>8}{'TEMP MiB':>10}{'OUT ROWS':>10}  INFO"
        lines.append(header)
        for part in analysis.profile.parts:
            duration = f"{part.duration:.3f}" if part.duration is not None else "-"
            cpu = f"{part.cpu:.1f}" if part.cpu is not None else "-"
            temp = f"{part.temp_db_ram_peak:.1f}" if part.temp_db_ram_peak is not None else "-"
            out_rows = str(part.out_rows) if part.out_rows is not None else "-"
            info = part.part_info or "-"
            lines.append(
                f"  {part.part_id:<4}{part.part_name:<{name_width}}{duration:>10}{cpu:>8}{temp:>10}{out_rows:>10}  {info}"
            )
        total = analysis.profile.total_duration()
        if total is not None:
            lines.append(f"  Total profiled duration: {total:.3f}s across {len(analysis.profile.parts)} part(s)")
    lines.append("")

    lines.extend(render_findings_block(analysis.findings, show_drill_down=False))
    lines.extend(render_ai_explanation_block(ai_explanation))

    return "\n".join(lines).rstrip() + "\n"
