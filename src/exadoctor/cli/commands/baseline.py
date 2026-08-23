"""`exadoctor baseline` command group -- local snapshot persistence and
trend comparison (roadmap Milestones 17-18).
"""

from __future__ import annotations

import json

import click

from exadoctor.baseline.compare import compare_snapshots, render_comparison_text
from exadoctor.baseline.history import build_trend, render_trend_text
from exadoctor.baseline.store import list_baselines, load_baseline, load_baseline_history, save_baseline
from exadoctor.cli.errors import handle_exadoctor_errors
from exadoctor.connection.config import ConnectionConfig
from exadoctor.connection.gateway import ReadOnlyGateway
from exadoctor.models.snapshot import build_snapshot


@click.group("baseline")
def baseline_group() -> None:
    """Save and compare local diagnostic baselines."""


@baseline_group.command("create")
@click.argument("name")
@handle_exadoctor_errors
def baseline_create_command(name: str) -> None:
    """Collect a fresh snapshot from the connected instance and save it as
    baseline NAME.

    Saving the same NAME again keeps the previous version rather than
    overwriting it -- see `exadoctor.baseline.store` for why.
    """
    config = ConnectionConfig.from_env()
    with ReadOnlyGateway(config) as gateway:
        snapshot = build_snapshot(gateway, config.host, config.port)

    save_baseline(name, snapshot)
    click.echo(f"Saved baseline {name!r} (collected {snapshot.collection_time.isoformat()}).")


@baseline_group.command("compare")
@click.argument("name")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
@handle_exadoctor_errors
def baseline_compare_command(name: str, output_format: str) -> None:
    """Collect a fresh snapshot from the connected instance and compare it
    against the most recently saved baseline NAME."""
    config = ConnectionConfig.from_env()
    with ReadOnlyGateway(config) as gateway:
        current = build_snapshot(gateway, config.host, config.port)

    baseline = load_baseline(name)
    result = compare_snapshots(baseline, current)

    if output_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(render_comparison_text(result))


@baseline_group.command("list")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
@handle_exadoctor_errors
def baseline_list_command(output_format: str) -> None:
    """List every saved baseline version, most recent first."""
    records = list_baselines()

    if output_format == "json":
        click.echo(json.dumps([{"name": r.name, "created_at": r.created_at.isoformat()} for r in records], indent=2))
        return

    if not records:
        click.echo("No baselines saved yet. Use `exadoctor baseline create <NAME>` to save one.")
        return

    for record in records:
        click.echo(f"{record.name}\t{record.created_at.isoformat()}")


@baseline_group.command("history")
@click.argument("name")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
@handle_exadoctor_errors
def baseline_history_command(name: str, output_format: str) -> None:
    """Show the trend across every saved version of baseline NAME.

    Does not connect to a database -- this reads only what's already saved
    locally via `exadoctor baseline create NAME` (possibly run several
    times over days/weeks). A metric missing at a given point (source
    unavailable, or too few samples) shows as "-", never a fabricated value.
    """
    snapshots = load_baseline_history(name)
    points = build_trend(snapshots)

    if output_format == "json":
        click.echo(json.dumps([p.to_dict() for p in points], indent=2))
    else:
        click.echo(render_trend_text(name, points))
