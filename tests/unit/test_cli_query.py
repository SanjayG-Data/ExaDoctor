from click.testing import CliRunner

from exadoctor.cli.main import cli


def test_query_help_shows_arguments():
    result = CliRunner().invoke(cli, ["query", "--help"])
    assert result.exit_code == 0
    assert "SESSION_ID" in result.output
    assert "STMT_ID" in result.output


def test_query_rejects_non_integer_session_id():
    result = CliRunner().invoke(cli, ["query", "not-a-number", "1"])
    assert result.exit_code != 0
    assert "not-a-number" in result.output


def test_query_reports_missing_configuration_cleanly():
    result = CliRunner().invoke(
        cli,
        ["query", "1", "1"],
        env={"EXADOCTOR_HOST": "", "EXADOCTOR_USER": "", "EXADOCTOR_PASSWORD": ""},
    )
    assert result.exit_code == 1
    assert "Missing required connection settings" in result.output
