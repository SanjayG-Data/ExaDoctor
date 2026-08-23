"""ExaDoctor command-line interface entry point."""

from __future__ import annotations

import sys


def _die_missing_dependency(exc: ModuleNotFoundError) -> None:
    # Every dependency-carrying import below is wrapped to reach here instead
    # of a raw traceback: a corrupted/partial install (e.g. a curl installer
    # that failed mid-`uv tool install`) previously crashed even
    # `exadoctor --help` with a bare ModuleNotFoundError, since `import
    # pyexasol` sits at module-load time in the gateway, ahead of every CLI
    # command and ahead of Click parsing anything. Confirmed live by
    # deliberately uninstalling pyexasol and running `exadoctor --help`.
    sys.stderr.write(
        f"exadoctor: missing required dependency {exc.name!r}. Your installation "
        "looks incomplete or corrupted. Reinstall with `uv tool install --force "
        "<path-or-git-url>` (or `uv sync` from a repo checkout).\n"
    )
    sys.exit(1)


try:
    import click
except ModuleNotFoundError as exc:
    _die_missing_dependency(exc)

from exadoctor import __version__

try:
    from exadoctor.cli.commands.baseline import baseline_group
    from exadoctor.cli.commands.capabilities import capabilities_command
    from exadoctor.cli.commands.query import query_command
    from exadoctor.cli.commands.scan import scan_command
except ModuleNotFoundError as exc:
    _die_missing_dependency(exc)


@click.group()
@click.version_option(version=__version__, prog_name="exadoctor")
def cli() -> None:
    """ExaDoctor: read-only diagnostic and workload-analysis CLI for Exasol."""


cli.add_command(capabilities_command)
cli.add_command(scan_command)
cli.add_command(query_command)
cli.add_command(baseline_group)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
