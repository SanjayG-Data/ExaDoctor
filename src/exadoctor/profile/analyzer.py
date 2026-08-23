"""Query analyzer (roadmap Milestone 9): correlates one statement's
EXA_SQL_LAST_DAY row with its profile and runs the deep profile rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from exadoctor.collectors.models import SqlStatement, json_safe
from exadoctor.collectors.workload import COLUMNS as _WORKLOAD_COLUMNS
from exadoctor.collectors.workload import row_to_sql_statement
from exadoctor.connection.gateway import SqlGateway
from exadoctor.errors import ExaDoctorError
from exadoctor.models.finding import Finding, FindingStatus
from exadoctor.profile.collector import collect_query_profile
from exadoctor.profile.models import QueryProfile
from exadoctor.profile.rules import evaluate_query_profile
from exadoctor.rules.policy import DEFAULT_POLICY, RulePolicy

_WORKLOAD_COLUMNS_CLAUSE = ", ".join(f'"{c}"' for c in _WORKLOAD_COLUMNS)


def _lookup_workload_row(gateway: SqlGateway, session_id: int, stmt_id: int) -> SqlStatement | None:
    # session_id/stmt_id are coerced to int by the CLI (click.argument(type=int))
    # before reaching here, so this cannot carry SQL metacharacters.
    sql = (
        f'SELECT {_WORKLOAD_COLUMNS_CLAUSE} FROM "EXA_STATISTICS"."EXA_SQL_LAST_DAY" '
        f'WHERE "SESSION_ID" = {int(session_id)} AND "STMT_ID" = {int(stmt_id)}'
    )
    try:
        result = gateway.execute(sql)
    except ExaDoctorError:
        return None
    if not result.rows:
        return None
    return row_to_sql_statement(result.rows[0])


@dataclass
class QueryAnalysis:
    session_id: int
    stmt_id: int
    workload: SqlStatement | None
    workload_available: bool
    profile: QueryProfile | None
    profile_available: bool
    findings: list[Finding]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "stmt_id": self.stmt_id,
            "workload_available": self.workload_available,
            "workload": json_safe(self.workload) if self.workload else None,
            "profile_available": self.profile_available,
            "profile": self.profile.to_dict() if self.profile else None,
            "findings": [f.to_dict() for f in self.findings],
        }


def analyze_query(
    gateway: SqlGateway, session_id: int, stmt_id: int, policy: RulePolicy = DEFAULT_POLICY
) -> QueryAnalysis:
    workload = _lookup_workload_row(gateway, session_id, stmt_id)
    profile = collect_query_profile(gateway, session_id, stmt_id)

    if profile is not None:
        findings = evaluate_query_profile(profile, policy)
    else:
        findings = [
            Finding(
                id="PERF-NO-PROFILE",
                title="No profile data",
                category="query",
                status=FindingStatus.NOT_EVALUATED,
                summary=(
                    f"No profile parts found in EXA_DBA_PROFILE_LAST_DAY or EXA_DBA_PROFILE_RUNNING "
                    f"for session {session_id}, statement {stmt_id}."
                ),
                confidence="LOW",
                requirements=["EXA_DBA_PROFILE_LAST_DAY", "EXA_DBA_PROFILE_RUNNING"],
                limitations=[
                    "Profiling may not have been enabled for this session, the statement may have "
                    "completed outside the profile retention window, or the session_id/stmt_id may not exist."
                ],
            )
        ]

    return QueryAnalysis(
        session_id=session_id,
        stmt_id=stmt_id,
        workload=workload,
        workload_available=workload is not None,
        profile=profile,
        profile_available=profile is not None,
        findings=findings,
    )
