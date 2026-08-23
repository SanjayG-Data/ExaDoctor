"""Runs every public-core rule against the golden fixture snapshot.

This exists specifically to catch a class of bug found during refinement:
the fixture's SessionInfo.login_time was timezone-aware while database_time
is naive (matching real Exasol data, which never carries tzinfo). Nothing
caught it because no existing test actually *evaluated* SESSION-LONG-001
(or any rule) against the golden fixture's data -- rule tests used their
own hand-built, already-consistent timestamps, and fixture tests only
checked serialization round-trips. Running the real rules against the real
fixture closes that gap.
"""

from __future__ import annotations

import json
from pathlib import Path

from exadoctor.models.snapshot import Snapshot
from exadoctor.rules import DEFAULT_POLICY, PUBLIC_CORE_RULES, run_rules

FIXTURE_PATH = Path(__file__).parent.parent / "golden" / "sample_snapshot.json"


def test_all_public_core_rules_run_against_the_golden_fixture_without_crashing() -> None:
    snapshot = Snapshot.from_dict(json.loads(FIXTURE_PATH.read_text()))

    findings = run_rules(PUBLIC_CORE_RULES, snapshot, DEFAULT_POLICY)

    assert len(findings) == len(PUBLIC_CORE_RULES) or len(findings) > 0
    # A rule that raises degrades to NOT_EVALUATED rather than propagating --
    # if the tz-aware/naive bug (or one like it) ever comes back, this
    # fails loudly with the rule's id and error message, not a bare crash.
    from exadoctor.models.finding import FindingStatus

    for finding in findings:
        if finding.status == FindingStatus.NOT_EVALUATED and "unexpected error" in finding.summary:
            raise AssertionError(f"Rule {finding.id} raised unexpectedly: {finding.summary}")
