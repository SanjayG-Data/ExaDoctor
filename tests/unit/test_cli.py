import subprocess
import sys

from click.testing import CliRunner

from exadoctor import __version__
from exadoctor.cli.main import cli


def test_help_works() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "ExaDoctor" in result.output


def test_version_flag_reports_version() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_missing_pyexasol_reports_a_clean_error_not_a_traceback() -> None:
    # Found while discussing installation: `import pyexasol` sits at
    # module-load time in the gateway, ahead of every CLI command and ahead
    # of Click parsing anything, so a corrupted/partial install (e.g. a curl
    # installer that failed mid-`uv tool install`) previously crashed even
    # `exadoctor --help` with a raw ModuleNotFoundError traceback -- confirmed
    # live by actually uninstalling pyexasol from the dev venv and running
    # the CLI. A subprocess is required here (not CliRunner): the failure is
    # in module import itself, which already succeeded once in this process.
    script = (
        "import sys; sys.modules['pyexasol'] = None; "
        "from exadoctor.cli.main import main; main()"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "missing required dependency 'pyexasol'" in result.stderr
