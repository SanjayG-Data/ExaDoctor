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

from exadoctor.models.snapshot import Snapshot
from exadoctor.report.terminal import render_ai_explanation_block, render_scan_text

FIXTURE_PATH = Path(__file__).parent.parent / "golden" / "sample_snapshot.json"


def _load_snapshot() -> Snapshot:
    return Snapshot.from_dict(json.loads(FIXTURE_PATH.read_text()))


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


def test_render_ai_explanation_block_empty_for_none_or_blank() -> None:
    assert render_ai_explanation_block(None) == []
    assert render_ai_explanation_block("") == []


def test_render_ai_explanation_block_contains_the_text() -> None:
    lines = render_ai_explanation_block("some explanation")
    assert "some explanation" in lines
