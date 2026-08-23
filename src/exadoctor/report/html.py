"""HTML renderer for `exadoctor scan` (roadmap Milestone 15).

Mirrors report/terminal.py's structure and philosophy: findings are grouped
by status, PASS is collapsed to a compact list (good news doesn't need
detail), and everything else -- CRITICAL, WARNING, INFO, NOT_EVALUATED,
NOT_APPLICABLE -- is shown in full (summary, recommendation, evidence,
limitations) so missing evidence is never silently invisible. The
capability/limitations section reuses `capabilities.report.build_report`
(the same source of truth `render_scan_text` uses) rather than
recomputing which sources are available or which derived diagnostics are
excluded by policy.

Self-contained by construction: every rule below exists to keep this a
single, standalone HTML string with no external network dependency.
  - All CSS is inlined in a single <style> block -- no <link> stylesheet.
  - No <script> tag at all: the only interactivity (collapsing the PASS
    list, and letting each other status section be collapsed too) uses
    the native HTML <details>/<summary> element, which needs zero JS.
  - Every piece of DB- or rule-sourced text (titles, summaries,
    recommendations, evidence values, limitations, capability reasons,
    host/version strings, etc.) is passed through `html.escape` before
    being embedded, so a value containing HTML-special characters can
    never inject markup into the report.
"""

from __future__ import annotations

import html as _html

from exadoctor.capabilities.report import build_report
from exadoctor.models.finding import Evidence, Finding, FindingStatus
from exadoctor.models.snapshot import Snapshot

_STATUS_ORDER = [
    FindingStatus.CRITICAL,
    FindingStatus.WARNING,
    FindingStatus.INFO,
    FindingStatus.NOT_EVALUATED,
    FindingStatus.NOT_APPLICABLE,
]

# (text color, background color, border color) per status -- used both for
# finding cards and for the small count badges in the summary line.
_STATUS_COLORS: dict[FindingStatus, tuple[str, str, str]] = {
    FindingStatus.CRITICAL: ("#7f1d1d", "#fef2f2", "#dc2626"),
    FindingStatus.WARNING: ("#78350f", "#fffbeb", "#d97706"),
    FindingStatus.INFO: ("#1e3a8a", "#eff6ff", "#2563eb"),
    FindingStatus.NOT_EVALUATED: ("#374151", "#f3f4f6", "#9ca3af"),
    FindingStatus.NOT_APPLICABLE: ("#374151", "#f9fafb", "#d1d5db"),
    FindingStatus.PASS: ("#14532d", "#f0fdf4", "#16a34a"),
}


def _esc(value: object) -> str:
    """Escape any value for safe embedding as HTML text content."""
    return _html.escape(str(value), quote=True)


def _status_class(status: FindingStatus) -> str:
    return f"status-{status.value.lower()}"


def _badge(status: FindingStatus, label: str | None = None) -> str:
    text_color, bg_color, border_color = _STATUS_COLORS[status]
    label = label if label is not None else status.value
    style = f"color:{text_color};background:{bg_color};border:1px solid {border_color};"
    return f'<span class="badge" style="{style}">{_esc(label)}</span>'


def _render_evidence(evidence: Evidence) -> str:
    ts = f" at {_esc(evidence.timestamp.isoformat())}" if evidence.timestamp else ""
    unit = f" {_esc(evidence.unit)}" if evidence.unit else ""
    context = f" &mdash; {_esc(evidence.context)}" if evidence.context else ""
    return (
        "<li><code>"
        f"{_esc(evidence.metric)}={_esc(evidence.value)}{unit}"
        "</code>"
        f"{ts} <span class=\"evidence-source\">[{_esc(evidence.source)}]</span>{context}</li>"
    )


def _render_finding_card(finding: Finding) -> str:
    _, bg_color, border_color = _STATUS_COLORS[finding.status]
    parts = [
        f'<div class="finding {_status_class(finding.status)}" '
        f'style="background:{bg_color};border-left:4px solid {border_color};">',
        '<div class="finding-header">',
        _badge(finding.status),
        f'<span class="finding-id">{_esc(finding.id)}</span>',
        f'<span class="finding-title">{_esc(finding.title)}</span>',
        "</div>",
        f'<p class="finding-summary">{_esc(finding.summary)}</p>',
    ]
    if finding.recommendation:
        parts.append(f'<p class="finding-recommendation"><strong>Recommendation:</strong> {_esc(finding.recommendation)}</p>')
    if finding.evidence:
        parts.append('<div class="finding-evidence"><strong>Evidence:</strong><ul>')
        parts.extend(_render_evidence(e) for e in finding.evidence)
        parts.append("</ul></div>")
    if finding.limitations:
        parts.append('<div class="finding-limitations"><strong>Limitations:</strong><ul>')
        parts.extend(f"<li>{_esc(limitation)}</li>" for limitation in finding.limitations)
        parts.append("</ul></div>")
    meta_bits = [f"category: {_esc(finding.category)}", f"confidence: {_esc(finding.confidence)}"]
    parts.append(f'<p class="finding-meta">{" &middot; ".join(meta_bits)}</p>')
    parts.append("</div>")
    return "\n".join(parts)


def _render_capabilities_section(snapshot: Snapshot) -> str:
    capability_report = build_report(snapshot.database.version, snapshot.capabilities)
    rows = []
    for cap in capability_report.capabilities:
        status_html = (
            '<span class="badge" style="color:#14532d;background:#f0fdf4;border:1px solid #16a34a;">AVAILABLE</span>'
            if cap.available
            else '<span class="badge" style="color:#7f1d1d;background:#fef2f2;border:1px solid #dc2626;">UNAVAILABLE</span>'
        )
        detail_bits = []
        if cap.available and cap.data_available is not None:
            detail_bits.append("data present" if cap.data_available else "no rows in window")
        if not cap.available and cap.reason:
            detail_bits.append(_esc(cap.reason))
        detail = " &mdash; ".join(detail_bits)
        rows.append(
            "<tr>"
            f"<td><code>{_esc(cap.id)}</code></td>"
            f"<td>{status_html}</td>"
            f"<td>{detail}</td>"
            "</tr>"
        )

    excluded_payload = capability_report.to_dict()["excluded_internal_derived_capabilities"]
    excluded_rows = []
    for name, info in excluded_payload.items():
        excluded_rows.append(
            "<tr>"
            f"<td><code>{_esc(name)}</code></td>"
            '<td><span class="badge" style="color:#374151;background:#f3f4f6;border:1px solid #9ca3af;">'
            "UNAVAILABLE BY POLICY</span></td>"
            f"<td>{_esc(info['reason'])}</td>"
            "</tr>"
        )

    return "\n".join(
        [
            '<section class="capabilities">',
            "<h2>Capabilities &amp; Limitations</h2>",
            "<p>Which sources this scan could actually read from -- so missing evidence is visible, not silent.</p>",
            "<table>",
            "<thead><tr><th>Source</th><th>Status</th><th>Detail</th></tr></thead>",
            "<tbody>",
            *rows,
            "</tbody>",
            "</table>",
            "<h3>Derived deep diagnostics (excluded by policy)</h3>",
            "<p>These require <code>$EXA_*</code> internal sources, which are out of scope for this build "
            "(see <code>docs/internal-interface-policy.md</code>). Listed explicitly rather than omitted.</p>",
            "<table>",
            "<thead><tr><th>Diagnostic</th><th>Status</th><th>Reason</th></tr></thead>",
            "<tbody>",
            *excluded_rows,
            "</tbody>",
            "</table>",
            "</section>",
        ]
    )


def _render_findings_summary(snapshot: Snapshot) -> str:
    counts = {status: 0 for status in FindingStatus}
    for finding in snapshot.findings:
        counts[finding.status] += 1
    badges = "".join(f"{_badge(status, f'{count} {status.value}')} " for status, count in counts.items() if count)
    return (
        f'<p class="findings-summary"><strong>{len(snapshot.findings)} findings total.</strong> {badges or "none"}</p>'
    )


def _render_pass_section(passing: list[Finding]) -> str:
    if not passing:
        return ""
    items = "".join(f'<li><code>{_esc(f.id)}</code> &mdash; {_esc(f.title)}</li>' for f in passing)
    return "\n".join(
        [
            "<details class=\"pass-section\">",
            f'<summary>{_badge(FindingStatus.PASS)} PASS ({len(passing)}) -- click to expand</summary>',
            f"<ul>{items}</ul>",
            "</details>",
        ]
    )


def _render_ai_explanation_section(ai_explanation: str | None) -> str:
    """Roadmap requirement: "AI output visibly separates explanation from
    deterministic evidence." Distinct heading, explicit disclaimer, and its
    own CSS class/accent color (violet) so it never reads as another
    finding card."""
    if not ai_explanation:
        return ""
    paragraphs = [p.strip() for p in ai_explanation.split("\n\n") if p.strip()] or [ai_explanation]
    paragraph_html = "\n".join(f"<p>{_esc(p)}</p>" for p in paragraphs)
    return "\n".join(
        [
            '<section class="ai-explanation">',
            "<h2>AI Explanation (unverified)</h2>",
            '<p class="ai-disclaimer"><strong>Generated by a local LLM, not part of the deterministic '
            "findings above.</strong> It may summarize or prioritize the findings and explain "
            "terminology, but cannot change any finding's severity or introduce new evidence, and it "
            "may be wrong. Always defer to the Findings section for facts.</p>",
            f'<div class="ai-explanation-text">{paragraph_html}</div>',
            "</section>",
        ]
    )


def _render_status_section(status: FindingStatus, findings: list[Finding]) -> str:
    matching = [f for f in findings if f.status == status]
    if not matching:
        return ""
    cards = "\n".join(_render_finding_card(f) for f in matching)
    return "\n".join(
        [
            "<details open>",
            f'<summary>{_badge(status)} {status.value} ({len(matching)})</summary>',
            cards,
            "</details>",
        ]
    )


_CSS = """
:root {
  color-scheme: light dark;
  --bg: #ffffff;
  --fg: #111827;
  --muted: #6b7280;
  --border: #e5e7eb;
  --card-bg: #f9fafb;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f172a;
    --fg: #e5e7eb;
    --muted: #9ca3af;
    --border: #334155;
    --card-bg: #1e293b;
  }
}
* { box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--fg);
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.5;
  margin: 0;
  padding: 2rem;
  max-width: 960px;
  margin-left: auto;
  margin-right: auto;
}
h1 { font-size: 1.6rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.25rem; margin-top: 2rem; border-bottom: 1px solid var(--border); padding-bottom: 0.25rem; }
h3 { font-size: 1.05rem; margin-top: 1.25rem; }
header.report-header {
  border-bottom: 2px solid var(--border);
  padding-bottom: 1rem;
  margin-bottom: 1rem;
}
header.report-header p { margin: 0.15rem 0; color: var(--muted); }
table { border-collapse: collapse; width: 100%; margin: 0.75rem 0; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
code {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 0.05rem 0.3rem;
  font-size: 0.9em;
}
.badge {
  display: inline-block;
  border-radius: 999px;
  padding: 0.1rem 0.6rem;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  margin-right: 0.35rem;
  white-space: nowrap;
}
.findings-summary { font-size: 1rem; }
details { margin: 1rem 0; }
details > summary {
  cursor: pointer;
  font-weight: 600;
  padding: 0.4rem 0;
  list-style: revert;
}
.finding {
  border-radius: 4px;
  padding: 0.75rem 1rem;
  margin: 0.6rem 0;
}
.finding-header { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.35rem; }
.finding-id { font-family: monospace; font-weight: 700; }
.finding-title { font-weight: 600; }
.finding-summary { margin: 0.3rem 0; }
.finding-recommendation { margin: 0.3rem 0; }
.finding-evidence ul, .finding-limitations ul, .pass-section ul { margin: 0.25rem 0; padding-left: 1.4rem; }
.finding-evidence li, .finding-limitations li { margin: 0.15rem 0; font-size: 0.92rem; }
.evidence-source { color: var(--muted); font-size: 0.85em; }
.finding-meta { color: var(--muted); font-size: 0.8rem; margin: 0.4rem 0 0 0; }
.pass-section summary { color: var(--muted); }
.ai-explanation {
  margin-top: 1.5rem;
  padding: 0.75rem 1rem;
  border-left: 4px solid #7c3aed;
  background: var(--card-bg);
  border-radius: 4px;
}
.ai-explanation h2 { border-bottom: none; margin-top: 0; color: #7c3aed; }
.ai-disclaimer { color: var(--muted); font-size: 0.85rem; }
.ai-explanation-text p { margin: 0.5rem 0; }
footer { margin-top: 2.5rem; color: var(--muted); font-size: 0.8rem; border-top: 1px solid var(--border); padding-top: 0.75rem; }
"""


def render_scan_html(snapshot: Snapshot, ai_explanation: str | None = None) -> str:
    """Render a self-contained HTML report for `exadoctor scan`.

    Mirrors `render_scan_text`'s content and grouping (see module
    docstring): a header, a capability/limitations section, a findings
    count summary, and findings grouped by status with PASS collapsed.
    Every dynamic string is HTML-escaped before embedding.

    `ai_explanation`, if given, renders in its own clearly-labeled,
    distinctly-colored section after the findings -- never mixed into the
    findings themselves (roadmap: AI output must visibly separate from
    deterministic evidence).
    """
    db = snapshot.database
    version = _esc(db.version) if db.version else "unknown"
    host_port = _esc(f"{db.host}:{db.port}")
    collected = _esc(snapshot.collection_time.isoformat())
    db_time = _esc(snapshot.database_time.isoformat()) if snapshot.database_time else None

    header_lines = [
        "<header class=\"report-header\">",
        "<h1>ExaDoctor Scan Report</h1>",
        f"<p><strong>Database:</strong> {version} @ {host_port}</p>",
        f"<p><strong>Collected:</strong> {collected}</p>",
    ]
    if db_time:
        header_lines.append(f"<p><strong>Database time:</strong> {db_time}</p>")
    header_lines.append("</header>")

    passing = [f for f in snapshot.findings if f.status == FindingStatus.PASS]

    body_parts = [
        "\n".join(header_lines),
        _render_capabilities_section(snapshot),
        '<section class="findings">',
        "<h2>Findings</h2>",
        _render_findings_summary(snapshot),
        _render_pass_section(passing),
    ]
    for status in _STATUS_ORDER:
        section = _render_status_section(status, snapshot.findings)
        if section:
            body_parts.append(section)
    body_parts.append("</section>")
    ai_section = _render_ai_explanation_section(ai_explanation)
    if ai_section:
        body_parts.append(ai_section)
    body_parts.append(
        '<footer>Generated by ExaDoctor &mdash; a read-only diagnostic report. '
        "No credentials or query text beyond what appears above are included.</footer>"
    )

    return "\n".join(
        [
            "<!DOCTYPE html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>ExaDoctor Scan Report &mdash; {version}</title>",
            f"<style>{_CSS}</style>",
            "</head>",
            "<body>",
            *body_parts,
            "</body>",
            "</html>",
            "",
        ]
    )
