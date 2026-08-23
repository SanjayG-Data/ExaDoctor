import json

from exadoctor.capabilities.models import Capability
from exadoctor.capabilities.report import build_report

AVAILABLE_CAP = Capability(
    id="EXA_SQL_LAST_DAY",
    available=True,
    reason=None,
    source='"EXA_STATISTICS"."EXA_SQL_LAST_DAY"',
    stability="PUBLIC",
    database_version="2026.1.0",
    privilege_required=None,
    detected_columns=["SESSION_ID", "STMT_ID"],
    missing_columns=[],
    data_available=True,
)

UNAVAILABLE_CAP = Capability(
    id="EXA_DBA_TRANSACTION_CONFLICTS",
    available=False,
    reason="ConnectionFailedError: insufficient privileges",
    source='"EXA_STATISTICS"."EXA_DBA_TRANSACTION_CONFLICTS"',
    stability="PUBLIC",
    database_version="2026.1.0",
    privilege_required="SELECT ANY DICTIONARY",
    detected_columns=[],
    missing_columns=["SESSION_ID"],
    data_available=None,
)


def test_report_to_dict_is_json_serializable() -> None:
    report = build_report("2026.1.0", [AVAILABLE_CAP, UNAVAILABLE_CAP])
    payload = json.dumps(report.to_dict())
    parsed = json.loads(payload)

    assert parsed["database_version"] == "2026.1.0"
    assert len(parsed["capabilities"]) == 2
    assert parsed["capabilities"][0]["id"] == "EXA_SQL_LAST_DAY"


def test_report_includes_excluded_internal_capabilities_explicitly() -> None:
    report = build_report(None, [AVAILABLE_CAP])
    payload = report.to_dict()

    excluded = payload["excluded_internal_derived_capabilities"]
    assert "IN_ROWS_OUT_ROWS_ANALYSIS" in excluded
    assert excluded["IN_ROWS_OUT_ROWS_ANALYSIS"]["available"] is False


def test_render_text_reports_available_and_unavailable_sources() -> None:
    report = build_report("2026.1.0", [AVAILABLE_CAP, UNAVAILABLE_CAP])
    text = report.render_text()

    assert "EXA_SQL_LAST_DAY" in text
    assert "AVAILABLE" in text
    assert "EXA_DBA_TRANSACTION_CONFLICTS" in text
    assert "UNAVAILABLE" in text
    assert "insufficient privileges" in text
    assert "NOT_AVAILABLE" in text  # excluded internal derived capabilities section
