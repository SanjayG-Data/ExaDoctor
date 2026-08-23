"""`exadoctor capabilities` command."""

from __future__ import annotations

import json

import click

from exadoctor.capabilities import PUBLIC_SOURCES, build_report, probe_all
from exadoctor.cli.errors import handle_exadoctor_errors
from exadoctor.connection.config import ConnectionConfig
from exadoctor.connection.gateway import ReadOnlyGateway


@click.command("capabilities")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
@handle_exadoctor_errors
def capabilities_command(output_format: str) -> None:
    """Probe the connected Exasol instance and report available diagnostic sources."""
    config = ConnectionConfig.from_env()
    with ReadOnlyGateway(config) as gateway:
        database_version, capabilities = probe_all(gateway, PUBLIC_SOURCES)

    report = build_report(database_version, capabilities)

    if output_format == "json":
        click.echo(json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(report.render_text())
