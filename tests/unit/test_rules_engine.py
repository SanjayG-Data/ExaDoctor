from rules_helpers import make_snapshot

from exadoctor.rules.engine import Rule, run_rules
from exadoctor.models.finding import Finding, FindingStatus
from exadoctor.rules.policy import DEFAULT_POLICY


def _passing_rule(snapshot, policy):
    return [Finding(id="OK-001", title="ok", category="test", status=FindingStatus.PASS, summary="fine")]


def _broken_rule(snapshot, policy):
    raise RuntimeError("boom")


def test_run_rules_collects_findings_from_all_rules():
    rules = [
        Rule(id="OK-001", title="ok", category="test", evaluate=_passing_rule),
        Rule(id="OK-002", title="ok2", category="test", evaluate=_passing_rule),
    ]
    findings = run_rules(rules, make_snapshot(), DEFAULT_POLICY)
    assert len(findings) == 2
    assert all(f.status == FindingStatus.PASS for f in findings)


def test_run_rules_survives_a_rule_that_raises():
    rules = [
        Rule(id="BROKEN-001", title="broken", category="test", evaluate=_broken_rule),
        Rule(id="OK-001", title="ok", category="test", evaluate=_passing_rule),
    ]
    findings = run_rules(rules, make_snapshot(), DEFAULT_POLICY)

    assert len(findings) == 2
    by_id = {f.id: f for f in findings}
    assert by_id["BROKEN-001"].status == FindingStatus.NOT_EVALUATED
    assert "boom" in by_id["BROKEN-001"].summary
    assert by_id["OK-001"].status == FindingStatus.PASS
