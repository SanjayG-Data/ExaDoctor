from click.testing import CliRunner

from exadoctor.cli.main import cli


def test_capabilities_command_reports_missing_configuration_cleanly() -> None:
    result = CliRunner().invoke(cli, ["capabilities"], env={
        "EXADOCTOR_HOST": "",
        "EXADOCTOR_USER": "",
        "EXADOCTOR_PASSWORD": "",
    })

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert result.output == (
        "Error: Missing required connection settings: "
        "EXADOCTOR_HOST, EXADOCTOR_USER, EXADOCTOR_PASSWORD. "
        "Set them as environment variables; ExaDoctor does not read "
        "credentials from files or CLI flags.\n"
    )
    assert "Traceback" not in result.output


def test_capabilities_help_lists_format_option() -> None:
    result = CliRunner().invoke(cli, ["capabilities", "--help"])
    assert result.exit_code == 0
    assert "--format" in result.output
