import pytest

from exadoctor.errors import NonReadOnlyStatementError
from exadoctor.connection.gateway import _strip_comments_respecting_strings, validate_select_only


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select * from sys.exa_metadata",
        "  SELECT * FROM t  ",
        "SELECT * FROM t;",
        "WITH cte AS (SELECT 1 AS x) SELECT x FROM cte",
        "-- leading comment\nSELECT 1",
        "/* block comment */ SELECT 1",
        "SELECT 1 -- trailing comment",
        # A semicolon inside a string literal is not a second statement.
        # Found by an independent code review: the original comment/
        # semicolon scanning was regex-based with no string-literal
        # awareness, so a perfectly safe single SELECT whose literal
        # happened to contain ';' was incorrectly rejected.
        "SELECT '; DROP TABLE x' AS y",
        "SELECT * FROM t WHERE x = 'a;b'",
        # '' is the SQL-standard escaped single quote -- must not be
        # mistaken for the string's closing quote (a real bug introduced
        # and caught, via testing, while fixing the case above: an
        # escape-pair check written against a `for i, ch in enumerate(...)`
        # loop cannot actually skip the second character of the pair).
        "SELECT 'it''s; not a real statement separator' AS x",
        "SELECT '--not a comment' AS x",
        "SELECT '/* not a comment either */' AS x",
    ],
)
def test_accepts_select_and_with_statements(sql: str) -> None:
    validate_select_only(sql)  # must not raise


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE t (x INT)",
        "ALTER TABLE t ADD COLUMN y INT",
        "DROP TABLE t",
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET x = 1",
        "DELETE FROM t",
        "MERGE INTO t USING s ON (t.x = s.x) WHEN MATCHED THEN UPDATE SET t.y = s.y",
        "KILL SESSION 123",
        "GRANT SELECT ON t TO u",
        "REVOKE SELECT ON t FROM u",
        "TRUNCATE TABLE t",
        "",
        "   ",
    ],
)
def test_rejects_non_select_statements(sql: str) -> None:
    with pytest.raises(NonReadOnlyStatementError):
        validate_select_only(sql)


def test_rejects_stacked_statements() -> None:
    with pytest.raises(NonReadOnlyStatementError):
        validate_select_only("SELECT 1; DROP TABLE t")


def test_rejects_stacked_statements_hidden_after_comment() -> None:
    with pytest.raises(NonReadOnlyStatementError):
        validate_select_only("SELECT 1 /* comment */; DROP TABLE t")


@pytest.mark.parametrize(
    "sql",
    [
        # Found by independent QA: without an explicit end-of-scan check,
        # an unterminated string literal left `in_string` permanently True,
        # so every character after it -- including a real ';' -- was
        # invisible to the stray-semicolon check. Exasol itself rejects an
        # unterminated literal as a syntax error; reject it here too.
        "SELECT 'unterminated; DROP TABLE x",
        "SELECT 'unterminated",
        "SELECT 1 WHERE x = 'still open",
    ],
)
def test_rejects_unterminated_string_literals(sql: str) -> None:
    with pytest.raises(NonReadOnlyStatementError, match="unterminated string literal"):
        validate_select_only(sql)


@pytest.mark.parametrize(
    "sql,expected",
    [
        # comment markers inside a string literal must survive untouched --
        # a naive regex-based stripper would corrupt these into truncated
        # (still-technically-SELECT-leading, but wrong) SQL instead of
        # raising, which is a silent-corruption bug, not a rejection bug.
        ("SELECT '--not a comment' AS x", "SELECT '--not a comment' AS x"),
        ("SELECT '/* not a comment either */' AS x", "SELECT '/* not a comment either */' AS x"),
        ("-- real comment\nSELECT 1", "\nSELECT 1"),
        ("/* real comment */ SELECT 1", "  SELECT 1"),
    ],
)
def test_strip_comments_respects_string_literals(sql: str, expected: str) -> None:
    assert _strip_comments_respecting_strings(sql) == expected
