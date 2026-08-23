"""Click-level error translation.

`ExaDoctorError` subclasses carry sanitized, actionable messages (see
exadoctor.errors). This decorator turns them into `click.ClickException`,
which Click prints as `Error: <message>` with no traceback and exit code 1 --
consistently whether the command is invoked through the installed console
script or through `CliRunner` in tests.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import TypeVar

import click

from exadoctor.errors import ExaDoctorError

F = TypeVar("F", bound=Callable[..., object])


def handle_exadoctor_errors(func: F) -> F:
    @functools.wraps(func)
    def wrapper(*args: object, **kwargs: object) -> object:
        try:
            return func(*args, **kwargs)
        except ExaDoctorError as exc:
            raise click.ClickException(str(exc)) from exc

    return wrapper  # type: ignore[return-value]
