"""CLI-level tests for `exadoctor baseline`.

No prior test invoked this command group through CliRunner at all -- every
previous check was a live manual run. `history` doesn't connect to a
database at all (it only reads the local SQLite store), so it's fully
testable here without mocking a gateway.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from exadoctor.baseline.store import save_baseline
from exadoctor.cli.main import cli
from exadoctor.models.snapshot import Snapshot

FIXTURE_PATH = Path(__file__).parent.parent / "golden" / "sample_snapshot.json"


def _load_snapshot() -> Snapshot:
    return Snapshot.from_dict(json.loads(FIXTURE_PATH.read_text()))


def test_baseline_group_help_lists_subcommands() -> None:
    result = CliRunner().invoke(cli, ["baseline", "--help"])
    assert result.exit_code == 0
    for name in ("create", "compare", "list", "history"):
        assert name in result.output


def test_baseline_create_reports_missing_configuration_cleanly() -> None:
    result = CliRunner().invoke(
        cli,
        ["baseline", "create", "production"],
        env={"EXADOCTOR_HOST": "", "EXADOCTOR_USER": "", "EXADOCTOR_PASSWORD": ""},
    )
    assert result.exit_code == 1
    assert "Missing required connection settings" in result.output


def test_baseline_history_empty_for_unknown_name(tmp_path: Path) -> None:
    db_path = str(tmp_path / "baselines.db")
    result = CliRunner().invoke(cli, ["baseline", "history", "never-saved"], env={"EXADOCTOR_BASELINE_DB": db_path})

    assert result.exit_code == 0
    assert "No saved baselines named" in result.output


def test_baseline_history_shows_saved_versions(tmp_path: Path) -> None:
    db_path = str(tmp_path / "baselines.db")
    save_baseline("production", _load_snapshot(), db_path=db_path)
    save_baseline("production", _load_snapshot(), db_path=db_path)

    result = CliRunner().invoke(
        cli, ["baseline", "history", "production", "--format", "json"], env={"EXADOCTOR_BASELINE_DB": db_path}
    )

    assert result.exit_code == 0
    points = json.loads(result.output)
    assert len(points) == 2
