import json
from datetime import datetime

from exadoctor.models.finding import Evidence, Finding, FindingStatus, not_evaluated


def test_finding_round_trips_through_json():
    finding = Finding(
        id="SYS-SWAP-001",
        title="Swap activity detected",
        category="system",
        status=FindingStatus.WARNING,
        summary="Swap observed",
        evidence=[
            Evidence(
                source="EXA_MONITOR_LAST_DAY",
                stability="PUBLIC",
                metric="SWAP",
                value=5.2,
                unit="MiB/s",
                timestamp=datetime(2026, 8, 22, 12, 0, 0),
                session_id=None,
            )
        ],
        recommendation="Investigate memory pressure.",
        confidence="HIGH",
        requirements=["EXA_MONITOR_LAST_DAY"],
        limitations=["cluster-maximum only"],
        documentation=["Exasol documentation"],
    )
    restored = Finding.from_dict(json.loads(json.dumps(finding.to_dict())))
    assert restored == finding


def test_severity_defaults_to_status_when_not_given():
    finding = Finding(id="X", title="t", category="c", status=FindingStatus.CRITICAL, summary="s")
    assert finding.severity == FindingStatus.CRITICAL


def test_not_evaluated_helper_never_returns_pass():
    finding = not_evaluated("X-001", "title", "category", reason="source unavailable")
    assert finding.status == FindingStatus.NOT_EVALUATED
    assert finding.status != FindingStatus.PASS
