"""Tests for the self-contained HTML scan report (roadmap Milestone 15).

Loads the golden fixture snapshot (no live DB needed) and checks the
rendered HTML looks valid, carries the expected data, and never contains
an external "http://"/"https://" URL -- the report must be fully
self-contained (no CDN scripts/fonts/images).
"""

from __future__ import annotations

import json
from pathlib import Path

from exadoctor.models.snapshot import Snapshot
from exadoctor.report.html import render_scan_html

FIXTURE_PATH = Path(__file__).parent.parent / "golden" / "sample_snapshot.json"


def _load_snapshot() -> Snapshot:
    data = json.loads(FIXTURE_PATH.read_text())
    return Snapshot.from_dict(data)


def test_render_scan_html_returns_a_complete_document() -> None:
    snapshot = _load_snapshot()
    rendered = render_scan_html(snapshot)

    assert rendered.strip().startswith("<!DOCTYPE html>")
    assert "<html" in rendered
    assert "</html>" in rendered
    assert "<style>" in rendered  # inline CSS, no external stylesheet


def test_render_scan_html_includes_database_and_finding_data() -> None:
    snapshot = _load_snapshot()
    rendered = render_scan_html(snapshot)

    assert snapshot.database.version is not None
    assert snapshot.database.version in rendered
    assert snapshot.database.host in rendered

    finding = snapshot.findings[0]
    assert finding.id in rendered
    assert finding.title in rendered
    assert finding.status.value in rendered


def test_render_scan_html_has_no_external_urls() -> None:
    snapshot = _load_snapshot()
    rendered = render_scan_html(snapshot)

    assert "http://" not in rendered
    assert "https://" not in rendered


def test_render_scan_html_lists_capabilities_and_excluded_derived_diagnostics() -> None:
    snapshot = _load_snapshot()
    rendered = render_scan_html(snapshot)

    for cap in snapshot.capabilities:
        assert cap.id in rendered

    # The three $EXA_*-excluded derived diagnostics must be listed
    # explicitly as unavailable-by-policy, not omitted.
    assert "IN_ROWS_OUT_ROWS_ANALYSIS" in rendered
    assert "NODE_SYNC_ANALYSIS" in rendered
    assert "PROCESS_SKEW_ANALYSIS" in rendered
    assert "UNAVAILABLE BY POLICY" in rendered


def test_render_scan_html_escapes_html_special_characters() -> None:
    snapshot = _load_snapshot()
    snapshot.findings[0].summary = "<script>alert('xss')</script> & \"quotes\""
    rendered = render_scan_html(snapshot)

    assert "<script>alert" not in rendered
    assert "&lt;script&gt;" in rendered


def test_render_scan_html_without_ai_explanation_has_no_ai_section() -> None:
    snapshot = _load_snapshot()
    rendered = render_scan_html(snapshot)
    # the CSS rule for .ai-explanation is always present (static stylesheet);
    # what must be absent is the actual rendered section element.
    assert 'class="ai-explanation"' not in rendered
    assert "AI Explanation" not in rendered


def test_render_scan_html_with_ai_explanation_shows_separated_section() -> None:
    snapshot = _load_snapshot()
    rendered = render_scan_html(snapshot, ai_explanation="Swap activity is worth a look.\n\nSecond paragraph.")

    assert 'class="ai-explanation"' in rendered
    assert "AI Explanation" in rendered
    assert "Swap activity is worth a look." in rendered
    assert "Second paragraph." in rendered
    assert "cannot change any finding" in rendered
    # must come after the findings section, not interleaved with it
    assert rendered.index("Findings</h2>") < rendered.index('class="ai-explanation"')


def test_render_scan_html_escapes_ai_explanation_text() -> None:
    snapshot = _load_snapshot()
    rendered = render_scan_html(snapshot, ai_explanation="<script>alert('xss')</script>")
    assert "<script>alert" not in rendered
    assert "&lt;script&gt;" in rendered


def test_render_scan_html_collapses_pass_findings_and_shows_others_in_full() -> None:
    snapshot = _load_snapshot()
    from exadoctor.models.finding import Finding, FindingStatus

    pass_finding = Finding(
        id="PASS-001",
        title="Everything looks fine",
        category="system",
        status=FindingStatus.PASS,
        summary="No issues detected.",
    )
    snapshot.findings.append(pass_finding)
    rendered = render_scan_html(snapshot)

    assert 'class="pass-section"' in rendered
    assert "PASS-001" in rendered
    # Non-PASS findings render as full cards (not just inside the
    # collapsed pass-section list).
    assert 'class="finding status-warning"' in rendered


def test_render_scan_html_shows_drill_down_for_evidence_with_session_and_stmt() -> None:
    """Same fix/gap as the text renderer: evidence pointing at a specific
    statement (e.g. SQL-SLOW-001) should surface the `exadoctor query`
    command for it, not just leave the reader to find the ids in raw JSON."""
    snapshot = _load_snapshot()
    from exadoctor.models.finding import Evidence, Finding, FindingStatus

    finding = Finding(
        id="SQL-SLOW-001",
        title="Duration outlier",
        category="workload",
        status=FindingStatus.WARNING,
        summary="Outlier statement.",
        evidence=[
            Evidence(
                source="EXA_SQL_LAST_DAY", stability="PUBLIC", metric="DURATION",
                value=1.0, unit="seconds", timestamp=None, session_id=42, stmt_id=7,
            )
        ],
    )
    snapshot.findings.append(finding)
    rendered = render_scan_html(snapshot)

    assert "exadoctor query 42 7" in rendered
