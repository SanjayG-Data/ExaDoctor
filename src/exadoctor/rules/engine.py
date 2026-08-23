"""DiagnosticRule interface and independent evaluation pipeline (Milestone 5).

Every rule receives the same Snapshot and RulePolicy and returns a list of
Findings. A rule that raises is caught here and converted into a
NOT_EVALUATED finding -- one broken rule must never abort the rest of the
scan (roadmap: "Rules must fail independently"). Rules never receive a
gateway/connection -- structurally, a rule cannot execute SQL.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from exadoctor.models.finding import Finding, FindingStatus
from exadoctor.models.snapshot import Snapshot
from exadoctor.rules.policy import RulePolicy

RuleFunc = Callable[[Snapshot, RulePolicy], list[Finding]]


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    category: str
    evaluate: RuleFunc


def run_rules(rules: list[Rule], snapshot: Snapshot, policy: RulePolicy) -> list[Finding]:
    findings: list[Finding] = []
    for rule in rules:
        try:
            findings.extend(rule.evaluate(snapshot, policy))
        except Exception as exc:  # noqa: BLE001 - one rule must never abort the scan
            findings.append(
                Finding(
                    id=rule.id,
                    title=rule.title,
                    category=rule.category,
                    status=FindingStatus.NOT_EVALUATED,
                    summary=f"Rule raised an unexpected error: {exc.__class__.__name__}: {exc}",
                    confidence="LOW",
                    limitations=["Rule evaluation failed; treat this as missing evidence, not a passing check."],
                )
            )
    return findings
