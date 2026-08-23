"""CLI-level tests for `exadoctor scan`.

No prior test invoked this command at all through CliRunner -- every
previous check was a live manual run. These tests close that gap for the
paths that don't need a live database (--help, missing config, and
--anonymize, which is exercised against a monkeypatched build_snapshot
rather than a real connection).
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from exadoctor.cli.main import cli
from exadoctor.models.snapshot import Snapshot

FIXTURE_PATH = Path(__file__).parent.parent / "golden" / "sample_snapshot.json"


def _load_snapshot() -> Snapshot:
    return Snapshot.from_dict(json.loads(FIXTURE_PATH.read_text()))


def test_scan_help_lists_all_flags() -> None:
    result = CliRunner().invoke(cli, ["scan", "--help"])
    assert result.exit_code == 0
    assert "--format" in result.output
    assert "--output" in result.output
    assert "--explain" in result.output
    assert "--anonymize" in result.output


def test_scan_reports_missing_configuration_cleanly() -> None:
    result = CliRunner().invoke(
        cli, ["scan"], env={"EXADOCTOR_HOST": "", "EXADOCTOR_USER": "", "EXADOCTOR_PASSWORD": ""}
    )
    assert result.exit_code == 1
    assert "Missing required connection settings" in result.output


def test_scan_output_to_an_unwritable_path_reports_a_clean_error_not_a_traceback(monkeypatch) -> None:
    # Found by independent QA: an ordinary typo'd --output directory
    # (parent doesn't exist) previously raised a raw FileNotFoundError
    # straight through main() -- a full Python traceback -- because
    # Path.write_text() wasn't wrapped in an ExaDoctorError the way every
    # other failure path in this tool is.
    snapshot = _load_snapshot()
    monkeypatch.setattr("exadoctor.cli.commands.scan.build_snapshot", lambda gateway, host, port: snapshot)
    monkeypatch.setattr("exadoctor.cli.commands.scan.ReadOnlyGateway.__enter__", lambda self: self)
    monkeypatch.setattr("exadoctor.cli.commands.scan.ReadOnlyGateway.__exit__", lambda self, *a: None)
    monkeypatch.setattr("exadoctor.cli.commands.scan.ReadOnlyGateway.connect", lambda self: None)

    env = {"EXADOCTOR_HOST": "irrelevant", "EXADOCTOR_USER": "irrelevant", "EXADOCTOR_PASSWORD": "irrelevant"}
    result = CliRunner().invoke(
        cli, ["scan", "--output", "/this/dir/does/not/exist/out.json"], env=env
    )

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "Error: Could not write report to" in result.output


def test_scan_anonymize_replaces_identity_before_rules_run(monkeypatch) -> None:
    # SESSION-LONG-001 embeds session.user_name directly into Finding.summary
    # text -- this is the exact case that requires anonymizing BEFORE running
    # rules rather than after (see scan.py's comment). Force a long session
    # so that rule actually fires against the fixture's real user_name "SYS".
    from datetime import timedelta

    # A distinctive value, not "SYS" -- the real Exasol system schema is
    # also literally named "SYS" and appears throughout the payload for
    # unrelated reasons (e.g. Capability.source = '"SYS"."EXA_METADATA"'),
    # which would make a substring check here a false positive either way.
    real_user = "REALUSER123"
    snapshot = _load_snapshot()
    snapshot.sessions.rows[0].user_name = real_user
    snapshot.sessions.rows[0].login_time = snapshot.database_time - timedelta(hours=5)

    monkeypatch.setattr("exadoctor.cli.commands.scan.build_snapshot", lambda gateway, host, port: snapshot)
    monkeypatch.setattr(
        "exadoctor.cli.commands.scan.ReadOnlyGateway.__enter__", lambda self: self
    )
    monkeypatch.setattr("exadoctor.cli.commands.scan.ReadOnlyGateway.__exit__", lambda self, *a: None)
    monkeypatch.setattr("exadoctor.cli.commands.scan.ReadOnlyGateway.connect", lambda self: None)

    env = {
        "EXADOCTOR_HOST": "irrelevant",
        "EXADOCTOR_USER": "irrelevant",
        "EXADOCTOR_PASSWORD": "irrelevant",
    }

    plain = CliRunner().invoke(cli, ["scan", "--format", "json"], env=env)
    anonymized = CliRunner().invoke(cli, ["scan", "--format", "json", "--anonymize"], env=env)

    assert plain.exit_code == 0
    assert anonymized.exit_code == 0

    plain_payload = json.loads(plain.output)
    anon_payload = json.loads(anonymized.output)

    # the real value must appear somewhere in the un-anonymized run (proves
    # the test scenario actually exercises the code path)...
    assert real_user in json.dumps(plain_payload)
    # ...and must not appear anywhere in the anonymized run, including
    # inside a rule-generated Finding.summary string.
    assert real_user not in json.dumps(anon_payload)

    session_long_findings = [f for f in anon_payload["findings"] if f["id"] == "SESSION-LONG-001"]
    assert session_long_findings, "expected the long-session rule to fire in this scenario"
    assert "USER_" in session_long_findings[0]["summary"]
