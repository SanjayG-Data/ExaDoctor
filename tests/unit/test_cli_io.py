from __future__ import annotations

from pathlib import Path

import pytest

from exadoctor.cli.io import write_report_output
from exadoctor.errors import OutputWriteError


def test_write_report_output_succeeds(tmp_path: Path) -> None:
    target = tmp_path / "report.txt"
    write_report_output(str(target), "hello")
    assert target.read_text() == "hello"


def test_write_report_output_wraps_oserror(tmp_path: Path) -> None:
    # Found by independent QA: this previously raised a raw
    # FileNotFoundError all the way through the CLI's main(), producing a
    # full Python traceback for an ordinary typo'd output directory.
    bad_path = tmp_path / "does-not-exist" / "report.txt"
    with pytest.raises(OutputWriteError, match="Could not write report"):
        write_report_output(str(bad_path), "hello")
