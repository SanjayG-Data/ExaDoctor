"""Direct tests for the terminal report renderer.

This module previously had NO test coverage at all for `render_scan_text`'s
success path -- a refactor left it calling a renamed-away private function,
and it went undetected until a live CLI run crashed. These tests exist
specifically to make sure that class of regression is caught by `pytest`,
not by happening to run the CLI live afterward.
"""

from __future__ import annotations

import json
from pathlib import Path

from exadoctor.models.finding import Evidence, Finding, FindingStatus
from exadoctor.models.snapshot import Snapshot
from exadoctor.report.terminal import render_ai_explanation_block, render_finding_lines, render_scan_text

FIXTURE_PATH = Path(__file__).parent.parent / "golden" / "sample_snapshot.json"


def _load_snapshot() -> Snapshot:
    return Snapshot.from_dict(json.loads(FIXTURE_PATH.read_text()))


def _finding_with_evidence(**evidence_kwargs) -> Finding:
    defaults = dict(source="EXA_SQL_LAST_DAY", stability="PUBLIC", metric="DURATION", value=1.0, unit="seconds", timestamp=None)
    defaults.update(evidence_kwargs)
    return Finding(
        id="SQL-SLOW-001",
        title="Duration outlier",
        category="workload",
        status=FindingStatus.WARNING,
        summary="Outlier statement.",
        evidence=[Evidence(**defaults)],
    )


def test_render_scan_text_runs_without_crashing_and_includes_key_data() -> None:
    snapshot = _load_snapshot()
    text = render_scan_text(snapshot)

    assert "EXADOCTOR SCAN REPORT" in text
    assert snapshot.database.version in text
    assert "FINDINGS" in text
    # the golden fixture's one Finding (SYS-SWAP-001, WARNING) must show up in full
    assert "SYS-SWAP-001" in text
    assert "WARNING" in text


def test_render_scan_text_without_ai_explanation_has_no_ai_section() -> None:
    snapshot = _load_snapshot()
    text = render_scan_text(snapshot)
    assert "AI EXPLANATION" not in text


def test_render_scan_text_with_ai_explanation_shows_a_clearly_separated_section() -> None:
    snapshot = _load_snapshot()
    text = render_scan_text(snapshot, ai_explanation="Swap activity is worth a look.")

    assert "AI EXPLANATION" in text
    assert "Swap activity is worth a look." in text
    # the disclaimer must appear, and must come after the real findings section
    findings_index = text.index("FINDINGS")
    ai_index = text.index("AI EXPLANATION")
    assert ai_index > findings_index
    assert "cannot change severity" in text


def test_render_finding_lines_shows_drill_down_when_session_and_stmt_present() -> None:
    """A user reading a WARNING about a specific statement had no way to
    get from the text report to `exadoctor query`'s required SESSION_ID/
    STMT_ID arguments without switching to --format json -- found via a
    real user asking exactly this question. This is the fix."""
    finding = _finding_with_evidence(session_id=42, stmt_id=7)
    lines = render_finding_lines(finding)
    evidence_line = next(line for line in lines if line.strip().startswith("evidence:"))
    assert "exadoctor query 42 7" in evidence_line


def test_render_finding_lines_omits_drill_down_when_stmt_id_missing() -> None:
    """SESSION-LONG-001-style evidence carries a session_id but no
    stmt_id (it's not about one statement) -- `exadoctor query` requires
    both, so no drill-down hint should be shown for a session-only id."""
    finding = _finding_with_evidence(session_id=42, stmt_id=None, metric="SESSION_AGE")
    lines = render_finding_lines(finding)
    evidence_line = next(line for line in lines if line.strip().startswith("evidence:"))
    assert "exadoctor query" not in evidence_line


def test_render_finding_lines_can_suppress_drill_down() -> None:
    finding = _finding_with_evidence(session_id=42, stmt_id=7)
    lines = render_finding_lines(finding, show_drill_down=False)
    evidence_line = next(line for line in lines if line.strip().startswith("evidence:"))
    assert "exadoctor query" not in evidence_line


def test_render_ai_explanation_block_empty_for_none_or_blank() -> None:
    assert render_ai_explanation_block(None) == []
    assert render_ai_explanation_block("") == []


def test_render_ai_explanation_block_contains_the_text() -> None:
    lines = render_ai_explanation_block("some explanation")
    assert "some explanation" in lines
