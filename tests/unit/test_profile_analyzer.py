from exadoctor.connection.gateway import QueryResult
from exadoctor.models.finding import FindingStatus
from exadoctor.profile.analyzer import analyze_query


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
