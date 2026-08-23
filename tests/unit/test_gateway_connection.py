import warnings

import pyexasol
import pytest
from pyexasol.warnings import PyexasolWarning

from exadoctor.connection.config import ConnectionConfig
from exadoctor.connection.gateway import ReadOnlyGateway
from exadoctor.errors import ConnectionFailedError

CONFIG = ConnectionConfig(
    host="unreachable.example.com",
    port=8563,
    user="test_user",
    password="super-secret-password",
)


class _FakeExaConnection:
    """Minimal stand-in matching what ExaError.__str__ actually reads.

    Real pyexasol always passes the (partially initialized) ExaConnection
    itself as `connection`, whose `.options` dict is populated before any
    connection attempt is made -- so `str(exc)` never touches a None here.
    """

    options = {"verbose_error": False}


def test_connect_wraps_pyexasol_errors_without_leaking_password(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_connect(**kwargs: object) -> None:
        raise pyexasol.ExaConnectionFailedError(_FakeExaConnection(), "connection refused")

    monkeypatch.setattr(pyexasol, "connect", fake_connect)

    gateway = ReadOnlyGateway(CONFIG)
    with pytest.raises(ConnectionFailedError) as exc_info:
        gateway.connect()

    message = str(exc_info.value)
    assert "super-secret-password" not in message
    assert "unreachable.example.com" in message
    assert "ExaConnectionFailedError" in message


def test_execute_without_connect_raises_actionable_error() -> None:
    gateway = ReadOnlyGateway(CONFIG)
    with pytest.raises(ConnectionFailedError, match="call connect"):
        gateway.execute("SELECT 1")


def test_connect_suppresses_pyexasol_default_cert_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    # Flagged by two independent review rounds: pyexasol emits a
    # PyexasolWarning on every encrypted connection made without a
    # fingerprint (real live behavior, confirmed against a self-signed
    # local instance) -- ExaDoctor has no config field for a fingerprint,
    # so this fires on every single command for that (common, on-prem)
    # setup. It describes a past pyexasol default-behavior change, not
    # anything an ExaDoctor user can act on -- pure stderr clutter.
    def fake_connect(**kwargs: object) -> str:
        warnings.warn("cert_reqs default changed", PyexasolWarning)
        return "fake-connection"

    monkeypatch.setattr(pyexasol, "connect", fake_connect)

    gateway = ReadOnlyGateway(CONFIG)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gateway.connect()

    assert not any(issubclass(w.category, PyexasolWarning) for w in caught)
