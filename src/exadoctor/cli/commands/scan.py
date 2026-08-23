"""`exadoctor scan` command -- database/workload health (roadmap Milestone 15)."""

from __future__ import annotations

import json

import click

from exadoctor.anonymizer import anonymize_snapshot
from exadoctor.cli.ai import maybe_explain
from exadoctor.cli.errors import handle_exadoctor_errors
from exadoctor.cli.io import write_report_output
from exadoctor.connection.config import ConnectionConfig
from exadoctor.connection.gateway import ReadOnlyGateway
from exadoctor.models.snapshot import build_snapshot
from exadoctor.report.html import render_scan_html
from exadoctor.report.terminal import render_scan_text
from exadoctor.rules import DEFAULT_POLICY, PUBLIC_CORE_RULES, run_rules


@click.command("scan")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json", "html"]),
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write the report to a file instead of stdout.",
)
@click.option(
    "--explain",
    "explain",
    is_flag=True,
    default=False,
    help=(
        "Add a plain-language AI explanation of the findings (requires "
        "EXADOCTOR_LLM_PROVIDER to be configured; optional -- the "
        "deterministic report above is always complete without it)."
    ),
)
@click.option(
    "--anonymize",
    "anonymize",
    is_flag=True,
    default=False,
    help=(
        "Replace host/username/cluster-name values with stable pseudonyms "
        "before reporting, for sharing the output (e.g. with Exasol "
        "support). Does not scrub free-text error messages/evidence "
        "context -- those may still carry identity fragments and should "
        "be reviewed before sharing."
    ),
)
@handle_exadoctor_errors
def scan_command(output_format: str, output_path: str | None, explain: bool, anonymize: bool) -> None:
    """Scan the connected Exasol instance for database/workload health issues."""
    config = ConnectionConfig.from_env()
    with ReadOnlyGateway(config) as gateway:
        snapshot = build_snapshot(gateway, config.host, config.port)

    if anonymize:
        # Anonymize BEFORE running rules, not after: SESSION-LONG-001 embeds
        # the raw user_name into its Finding.summary text, and there is no
        # reliable way to scrub an already-generated string after the fact
        # (see the anonymizer module's own documented refusal to do
        # free-text scanning). Anonymizing first means every rule reads
        # already-pseudonymized session/cluster data, so generated finding
        # text is correct by construction.
        snapshot = anonymize_snapshot(snapshot).snapshot

    snapshot.findings = run_rules(PUBLIC_CORE_RULES, snapshot, DEFAULT_POLICY)
    ai_explanation = maybe_explain(snapshot.findings, explain)

    if output_format == "json":
        payload = snapshot.to_dict()
        if explain:
            payload["ai_explanation"] = ai_explanation
        rendered = json.dumps(payload, indent=2)
    elif output_format == "html":
        rendered = render_scan_html(snapshot, ai_explanation=ai_explanation)
    else:
        rendered = render_scan_text(snapshot, ai_explanation=ai_explanation)

    if output_path:
        write_report_output(output_path, rendered)
        click.echo(f"Report written to {output_path}")
    else:
        click.echo(rendered)
