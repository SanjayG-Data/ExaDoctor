from exadoctor.connection.gateway import QueryResult
from exadoctor.errors import ConnectionFailedError
from exadoctor.models.finding import FindingStatus
from exadoctor.profile.analyzer import analyze_query, list_session_statements


class ScriptedGateway:
    def __init__(self, responses: dict[str, QueryResult]):
        self.responses = responses

    def execute(self, sql: str) -> QueryResult:
        for key, response in self.responses.items():
            if key in sql:
                return response
        raise AssertionError(f"ScriptedGateway has no response matching: {sql!r}")


_WORKLOAD_ROW = (
    1874035687682015232,
    133,
    "SELECT",
    "DQL",
    0.5,
    None,
    None,
    4.5,
    1.0,
    0.0,
    0.0,
    0.0,
    True,
    None,
    None,
    50,
    "MAIN",
)
_PROFILE_ROW = (1, "SCAN", None, "S", "T", 100, 50, 0.5, 4.5, 1.0, 0.0, 0.0, 0.0, None)


def test_analyze_query_correlates_workload_and_profile():
    gateway = ScriptedGateway(
        {
            "EXA_SQL_LAST_DAY": QueryResult(columns=[], rows=[_WORKLOAD_ROW]),
            "EXA_DBA_PROFILE_LAST_DAY": QueryResult(columns=[], rows=[_PROFILE_ROW]),
            "EXA_DBA_PROFILE_RUNNING": QueryResult(columns=[], rows=[]),
        }
    )
    analysis = analyze_query(gateway, session_id=1874035687682015232, stmt_id=133)

    assert analysis.workload_available is True
    assert analysis.workload.command_name == "SELECT"
    assert analysis.profile_available is True
    assert len(analysis.findings) > 0


def test_analyze_query_handles_missing_workload_row():
    gateway = ScriptedGateway(
        {
            "EXA_SQL_LAST_DAY": QueryResult(columns=[], rows=[]),
            "EXA_DBA_PROFILE_LAST_DAY": QueryResult(columns=[], rows=[_PROFILE_ROW]),
            "EXA_DBA_PROFILE_RUNNING": QueryResult(columns=[], rows=[]),
        }
    )
    analysis = analyze_query(gateway, session_id=1, stmt_id=1)
    assert analysis.workload_available is False
    assert analysis.profile_available is True


def test_analyze_query_reports_not_evaluated_when_no_profile():
    gateway = ScriptedGateway(
        {
            "EXA_SQL_LAST_DAY": QueryResult(columns=[], rows=[_WORKLOAD_ROW]),
            "EXA_DBA_PROFILE_LAST_DAY": QueryResult(columns=[], rows=[]),
            "EXA_DBA_PROFILE_RUNNING": QueryResult(columns=[], rows=[]),
        }
    )
    analysis = analyze_query(gateway, session_id=1874035687682015232, stmt_id=133)
    assert analysis.profile_available is False
    assert analysis.findings[0].status == FindingStatus.NOT_EVALUATED
    assert analysis.findings[0].id == "PERF-NO-PROFILE"


_SECOND_WORKLOAD_ROW = (
    1874035687682015232,
    134,
    "COMMIT",
    "TRANSACTION",
    0.001,
    None,
    None,
    1.0,
    None,
    0.0,
    0.0,
    0.0,
    True,
    None,
    None,
    0,
    "MAIN",
)


def test_list_session_statements_returns_every_row_for_the_session():
    gateway = ScriptedGateway(
        {"EXA_SQL_LAST_DAY": QueryResult(columns=[], rows=[_WORKLOAD_ROW, _SECOND_WORKLOAD_ROW])}
    )
    result = list_session_statements(gateway, session_id=1874035687682015232)

    assert result.available is True
    assert result.session_id == 1874035687682015232
    assert [s.stmt_id for s in result.statements] == [133, 134]


def test_list_session_statements_empty_for_a_session_with_no_statements():
    gateway = ScriptedGateway({"EXA_SQL_LAST_DAY": QueryResult(columns=[], rows=[])})
    result = list_session_statements(gateway, session_id=999)

    assert result.available is True
    assert result.statements == []


def test_list_session_statements_degrades_gracefully_on_query_failure():
    class FailingGateway:
        def execute(self, sql: str) -> QueryResult:
            raise ConnectionFailedError("object EXA_SQL_LAST_DAY not found")

    result = list_session_statements(FailingGateway(), session_id=1)

    assert result.available is False
    assert "not found" in (result.reason or "")
    assert result.statements == []


def test_list_session_statements_to_dict_is_json_serializable():
    import json

    gateway = ScriptedGateway({"EXA_SQL_LAST_DAY": QueryResult(columns=[], rows=[_WORKLOAD_ROW])})
    result = list_session_statements(gateway, session_id=1874035687682015232)
    payload = json.dumps(result.to_dict())
    assert "SELECT" in payload


def test_analyze_query_to_dict_is_json_serializable():
    import json

    gateway = ScriptedGateway(
        {
            "EXA_SQL_LAST_DAY": QueryResult(columns=[], rows=[_WORKLOAD_ROW]),
            "EXA_DBA_PROFILE_LAST_DAY": QueryResult(columns=[], rows=[_PROFILE_ROW]),
            "EXA_DBA_PROFILE_RUNNING": QueryResult(columns=[], rows=[]),
        }
    )
    analysis = analyze_query(gateway, session_id=1874035687682015232, stmt_id=133)
    payload = json.dumps(analysis.to_dict())
    assert "SELECT" in payload
