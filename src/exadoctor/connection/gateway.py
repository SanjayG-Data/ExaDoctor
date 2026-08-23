"""Read-only SQL execution gateway.

Every collector must go through `ReadOnlyGateway.execute()`. It accepts a
single SELECT/WITH statement and rejects everything else -- administrative
commands, DML, and multi-statement input -- before any SQL reaches Exasol.
"""

from __future__ import annotations

import re
import ssl
import warnings
from dataclasses import dataclass
from typing import Any, Protocol

import pyexasol
from pyexasol.warnings import PyexasolWarning

from exadoctor.connection.config import ConnectionConfig
from exadoctor.errors import ConnectionFailedError, NonReadOnlyStatementError

_ALLOWED_LEADING_KEYWORDS = ("SELECT", "WITH")
_LEADING_WORD_RE = re.compile(r"[A-Za-z]+")


def _strip_comments_respecting_strings(sql: str) -> str:
    """Remove `--` line comments and `/* */` block comments -- but never
    inside a single-quoted string literal (`''` is the SQL-standard escaped
    quote). A naive regex-based stripper (the original implementation) would
    treat `--`/`/*` appearing inside a string literal as real comment
    markers, corrupting the literal; confirmed live this incorrectly
    rejected a perfectly safe single SELECT whose literal happened to
    contain a semicolon, via the same string-literal blindness in the
    semicolon check below."""
    out: list[str] = []
    i = 0
    n = len(sql)
    in_string = False
    while i < n:
        ch = sql[i]
        if in_string:
            out.append(ch)
            if ch == "'":
                if sql[i + 1 : i + 2] == "'":
                    out.append("'")
                    i += 2
                    continue
                in_string = False
            i += 1
            continue

        if ch == "'":
            in_string = True
            out.append(ch)
            i += 1
            continue

        if sql[i : i + 2] == "--":
            newline_at = sql.find("\n", i)
            if newline_at == -1:
                break  # trailing line comment with nothing after it
            out.append("\n")
            i = newline_at + 1
            continue

        if sql[i : i + 2] == "/*":
            end_at = sql.find("*/", i + 2)
            if end_at == -1:
                out.append(sql[i:])  # unterminated block comment: leave as-is
                break
            out.append(" ")
            i = end_at + 2
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _scan_for_violations(sql: str) -> tuple[bool, bool]:
    """Single pass over `sql` (already comment-stripped): returns
    `(has_stray_semicolon, ends_inside_unterminated_string)`.

    `has_stray_semicolon` is True if `sql` contains a `;` outside a
    single-quoted string literal, other than exactly one at the very end.

    `ends_inside_unterminated_string` is True if a `'` was opened and never
    closed. Found by independent QA: without this check, an unterminated
    literal (`SELECT 'unterminated; DROP TABLE x`) was silently ACCEPTED --
    once `in_string` never toggles back off, every character to the end of
    input, including a real `;`, reads as "inside a string" and the
    semicolon check never fires. Exasol itself rejects an unterminated
    literal as a syntax error, so treating it as invalid here too matches
    server-side behavior rather than passing malformed SQL through
    unexamined.

    Uses an explicit index loop, not `for i, ch in enumerate(...)`: an
    escaped `''` pair must advance past *both* characters in one step, and
    mutating the loop variable inside a `for`/`enumerate` loop does not
    skip the next iteration in Python -- an earlier version of this
    function used that pattern and silently mis-detected the second quote
    of an escape pair as a real closing quote, caught by testing
    `'it''s; ...'` (one string literal, no real second statement) before
    this was ever shipped.
    """
    body = sql[:-1] if sql.rstrip().endswith(";") else sql
    in_string = False
    has_semicolon = False
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if in_string:
            if ch == "'":
                if body[i + 1 : i + 2] == "'":
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if ch == "'":
            in_string = True
        elif ch == ";":
            has_semicolon = True
        i += 1
    return has_semicolon, in_string


def validate_select_only(sql: str) -> None:
    """Raise NonReadOnlyStatementError unless `sql` is a single SELECT/WITH statement."""
    stripped = _strip_comments_respecting_strings(sql).strip()
    if not stripped:
        raise NonReadOnlyStatementError("Empty statement is not allowed.")

    has_stray_semicolon, ends_unterminated = _scan_for_violations(stripped)
    if ends_unterminated:
        raise NonReadOnlyStatementError("Statement contains an unterminated string literal.")
    if has_stray_semicolon:
        raise NonReadOnlyStatementError(
            "Multiple statements are not allowed through the read-only gateway."
        )

    match = _LEADING_WORD_RE.match(stripped)
    leading_keyword = match.group(0).upper() if match else ""
    if leading_keyword not in _ALLOWED_LEADING_KEYWORDS:
        raise NonReadOnlyStatementError(
            f"Statement must start with SELECT or WITH, got {leading_keyword or '<empty>'!r}."
        )


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]


class SqlGateway(Protocol):
    """Structural type for anything that can run a read-only query.

    Probes and future collectors depend on this, not on `ReadOnlyGateway`
    directly, so they can be exercised in unit tests against fixture/fake
    gateways without a live Exasol connection.
    """

    def execute(self, sql: str) -> QueryResult: ...


class ReadOnlyGateway:
    """Wraps a pyexasol connection and enforces SELECT-only access."""

    def __init__(self, config: ConnectionConfig) -> None:
        self._config = config
        self._connection: pyexasol.ExaConnection | None = None

    def connect(self) -> None:
        sslopt = {"cert_reqs": ssl.CERT_NONE} if self._config.tls_insecure else None
        try:
            # ExaDoctor never accepts a certificate fingerprint (it has no
            # config field for one), so an encrypted connection with
            # tls_insecure=False always takes pyexasol's own strict-by-
            # default path. pyexasol emits a PyexasolWarning on every such
            # connection describing that default as a past behavior change
            # -- informational library changelog noise, not something an
            # ExaDoctor user can act on, since there is no fingerprint
            # option to set. Flagged as stderr clutter by two independent
            # review rounds; suppressed narrowly (this warning class only,
            # only around this call) rather than globally.
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=PyexasolWarning)
                self._connection = pyexasol.connect(
                    dsn=f"{self._config.host}:{self._config.port}",
                    user=self._config.user,
                    password=self._config.password,
                    schema=self._config.schema or "",
                    encryption=self._config.encryption,
                    compression=True,
                    fetch_dict=False,
                    # Without this, pyexasol returns raw wire-format strings for
                    # any DECIMAL with nonzero scale and for every TIMESTAMP/DATE
                    # column instead of Decimal/datetime/date -- confirmed live
                    # against EXA_ALL_SESSIONS.LOGIN_TIME and EXA_SQL_LAST_DAY.CPU.
                    fetch_mapper=pyexasol.exasol_mapper,
                    websocket_sslopt=sslopt,
                )
        except pyexasol.ExaError as exc:
            raise ConnectionFailedError(
                f"Could not connect to Exasol at {self._config.host}:{self._config.port} "
                f"as user {self._config.user!r}: {exc.__class__.__name__}: {exc}"
            ) from exc

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> ReadOnlyGateway:
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def execute(self, sql: str) -> QueryResult:
        validate_select_only(sql)
        if self._connection is None:
            raise ConnectionFailedError("Gateway is not connected; call connect() first.")

        try:
            statement = self._connection.execute(sql)
            columns = list(statement.columns().keys())
            rows = statement.fetchall()
        except pyexasol.ExaError as exc:
            raise ConnectionFailedError(
                f"Query failed against Exasol at {self._config.host}:{self._config.port}: "
                f"{exc.__class__.__name__}: {exc}"
            ) from exc

        return QueryResult(columns=columns, rows=rows)
