"""`exadoctor query <SESSION_ID> <STMT_ID>` -- deep query root-cause analysis (Milestone 9)."""

from __future__ import annotations

import json

import click

from exadoctor.cli.ai import maybe_explain
from exadoctor.cli.errors import handle_exadoctor_errors
from exadoctor.connection.config import ConnectionConfig
from exadoctor.connection.gateway import ReadOnlyGateway
from exadoctor.profile.analyzer import analyze_query
from exadoctor.report.query_text import render_query_text


@click.command("query")
@click.argument("session_id", type=int)
@click.argument("stmt_id", type=int)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
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
@handle_exadoctor_errors
def query_command(session_id: int, stmt_id: int, output_format: str, explain: bool) -> None:
    """Deep root-cause analysis for one statement, identified by SESSION_ID and STMT_ID."""
    config = ConnectionConfig.from_env()
    with ReadOnlyGateway(config) as gateway:
        analysis = analyze_query(gateway, session_id, stmt_id)

    ai_explanation = maybe_explain(analysis.findings, explain)

    if output_format == "json":
        payload = analysis.to_dict()
        if explain:
            payload["ai_explanation"] = ai_explanation
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(render_query_text(analysis, ai_explanation=ai_explanation))
