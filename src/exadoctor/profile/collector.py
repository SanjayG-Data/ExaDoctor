"""Query profile collector: EXA_DBA_PROFILE_LAST_DAY with EXA_DBA_PROFILE_RUNNING fallback.

Public-only (see docs/internal-interface-policy.md). Column list matches
what Milestone 0 verified live for both sources.

Deliberately does NOT select SQL_TEXT even though both source tables carry
it (roadmap section 12.2: "SQL text excluded from shareable output by
default... collected only where required and explicitly permitted") --
nothing in this codebase's profile rules or reports reads it, so there is
no requirement to justify collecting it. (An earlier version of this
collector did select it, which silently contradicted docs/security.md's
claim that no collector does -- caught by an independent code review.)
"""

from __future__ import annotations

from exadoctor.connection.gateway import SqlGateway
from exadoctor.errors import ExaDoctorError
from exadoctor.profile.models import QueryProfile, QueryProfilePart

_COLUMNS = (
    "PART_ID",
    "PART_NAME",
    "PART_INFO",
    "OBJECT_SCHEMA",
    "OBJECT_NAME",
    "OBJECT_ROWS",
    "OUT_ROWS",
    "DURATION",
    "CPU",
    "TEMP_DB_RAM_PEAK",
    "LOCAL_READ_SIZE",
    "REMOTE_READ_SIZE",
    "NET",
    "REMARKS",
)


def _build_sql(table: str, session_id: int, stmt_id: int) -> str:
    columns_clause = ", ".join(f'"{c}"' for c in _COLUMNS)
    # session_id/stmt_id are coerced to int by the CLI layer before reaching
    # here, so this cannot carry SQL metacharacters regardless of caller input.
    return (
        f"SELECT {columns_clause} FROM \"EXA_STATISTICS\".\"{table}\" "
        f'WHERE "SESSION_ID" = {int(session_id)} AND "STMT_ID" = {int(stmt_id)} '
        f'ORDER BY "PART_ID"'
    )


def _row_to_part(row: tuple) -> QueryProfilePart:
    (
        part_id,
        part_name,
        part_info,
        object_schema,
        object_name,
        object_rows,
        out_rows,
        duration,
        cpu,
        temp_db_ram_peak,
        local_read_size,
        remote_read_size,
        net,
        remarks,
    ) = row
    return QueryProfilePart(
        part_id=part_id,
        part_name=part_name,
        part_info=part_info,
        object_schema=object_schema,
        object_name=object_name,
        object_rows=object_rows,
        in_rows=None,
        out_rows=out_rows,
        duration=float(duration) if duration is not None else None,
        cpu=float(cpu) if cpu is not None else None,
        temp_db_ram_peak=float(temp_db_ram_peak) if temp_db_ram_peak is not None else None,
        mem_peak=None,
        local_read_size=float(local_read_size) if local_read_size is not None else None,
        remote_read_size=float(remote_read_size) if remote_read_size is not None else None,
        network=float(net) if net is not None else None,
        process_id=None,
        node_id=None,
        start_time=None,
        stop_time=None,
        remarks=remarks,
    )


def _try_source(gateway: SqlGateway, table: str, session_id: int, stmt_id: int) -> QueryProfile | None:
    try:
        result = gateway.execute(_build_sql(table, session_id, stmt_id))
    except ExaDoctorError:
        return None
    if not result.rows:
        return None
    parts = [_row_to_part(row) for row in result.rows]
    return QueryProfile(session_id=session_id, stmt_id=stmt_id, source=table, parts=parts)


def collect_query_profile(gateway: SqlGateway, session_id: int, stmt_id: int) -> QueryProfile | None:
    """Look up a statement's profile: completed (LAST_DAY) first, then RUNNING.

    Returns None if neither source has rows for this session/statement --
    the caller is responsible for reporting NOT_EVALUATED/not-found, not
    this function.
    """
    profile = _try_source(gateway, "EXA_DBA_PROFILE_LAST_DAY", session_id, stmt_id)
    if profile is not None:
        return profile
    return _try_source(gateway, "EXA_DBA_PROFILE_RUNNING", session_id, stmt_id)
