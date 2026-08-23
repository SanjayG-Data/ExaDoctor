from exadoctor.connection.gateway import QueryResult
from exadoctor.errors import ConnectionFailedError
from exadoctor.profile.collector import collect_query_profile


class ScriptedGateway:
    def __init__(self, responses: dict[str, QueryResult | Exception]):
        self.responses = responses
        self.queries: list[str] = []

    def execute(self, sql: str) -> QueryResult:
        self.queries.append(sql)
        for key, response in self.responses.items():
            if key in sql:
                if isinstance(response, Exception):
                    raise response
                return response
        raise AssertionError(f"ScriptedGateway has no response matching: {sql!r}")


_ROW = (1, "SCAN", "GLOBAL", "S", "T", 100, 50, 0.5, 4.5, 1.0, 0.0, 0.0, 0.0, None)


def test_collect_query_profile_prefers_last_day():
    gateway = ScriptedGateway(
        {
            "EXA_DBA_PROFILE_LAST_DAY": QueryResult(columns=[], rows=[_ROW]),
            "EXA_DBA_PROFILE_RUNNING": QueryResult(columns=[], rows=[]),
        }
    )
    profile = collect_query_profile(gateway, session_id=1, stmt_id=1)
    assert profile is not None
    assert profile.source == "EXA_DBA_PROFILE_LAST_DAY"
    assert profile.parts[0].part_name == "SCAN"


def test_collect_query_profile_falls_back_to_running():
    gateway = ScriptedGateway(
        {
            "EXA_DBA_PROFILE_LAST_DAY": QueryResult(columns=[], rows=[]),
            "EXA_DBA_PROFILE_RUNNING": QueryResult(columns=[], rows=[_ROW]),
        }
    )
    profile = collect_query_profile(gateway, session_id=1, stmt_id=1)
    assert profile is not None
    assert profile.source == "EXA_DBA_PROFILE_RUNNING"


def test_collect_query_profile_returns_none_when_neither_has_rows():
    gateway = ScriptedGateway(
        {
            "EXA_DBA_PROFILE_LAST_DAY": QueryResult(columns=[], rows=[]),
            "EXA_DBA_PROFILE_RUNNING": QueryResult(columns=[], rows=[]),
        }
    )
    assert collect_query_profile(gateway, session_id=1, stmt_id=1) is None


def test_collect_query_profile_returns_none_on_query_error():
    gateway = ScriptedGateway(
        {
            "EXA_DBA_PROFILE_LAST_DAY": ConnectionFailedError("insufficient privileges"),
            "EXA_DBA_PROFILE_RUNNING": ConnectionFailedError("insufficient privileges"),
        }
    )
    assert collect_query_profile(gateway, session_id=1, stmt_id=1) is None
