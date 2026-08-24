"""Registry of public Exasol sources ExaDoctor probes.

Every entry here (schema, table, and required columns) was verified against
a live Exasol 2026.1.0 instance -- see docs/capability-matrix.md for the
raw DESCRIBE/SELECT evidence.

$EXA_* internal sources are intentionally absent: see
docs/internal-interface-policy.md for that decision.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    id: str
    schema: str
    table: str
    required_columns: tuple[str, ...]
    privilege_required: str | None = None

    @property
    def qualified_name(self) -> str:
        return f'"{self.schema}"."{self.table}"'


PUBLIC_SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        id="EXA_METADATA",
        schema="SYS",
        table="EXA_METADATA",
        required_columns=("PARAM_NAME", "PARAM_VALUE"),
    ),
    SourceSpec(
        id="EXA_PARAMETERS",
        schema="SYS",
        table="EXA_PARAMETERS",
        required_columns=("PARAMETER_NAME", "SESSION_VALUE", "SYSTEM_VALUE"),
    ),
    SourceSpec(
        id="EXA_ALL_SESSIONS",
        schema="SYS",
        table="EXA_ALL_SESSIONS",
        required_columns=(
            "SESSION_ID",
            "USER_NAME",
            "STATUS",
            "COMMAND_NAME",
            "STMT_ID",
            "DURATION",
            "LOGIN_TIME",
            "TEMP_DB_RAM",
            "PERSISTENT_DB_RAM",
            "CONSUMER_GROUP",
            "CLUSTER_NAME",
        ),
    ),
    SourceSpec(
        id="EXA_DBA_SESSIONS",
        schema="SYS",
        table="EXA_DBA_SESSIONS",
        required_columns=(
            "SESSION_ID",
            "USER_NAME",
            "EFFECTIVE_USER",
            "STATUS",
            "COMMAND_NAME",
            "STMT_ID",
            "DURATION",
            "LOGIN_TIME",
            "HOST",
            "OS_USER",
            "CLUSTER_NAME",
        ),
        privilege_required="SELECT ANY DICTIONARY",
    ),
    SourceSpec(
        id="EXA_SQL_LAST_DAY",
        schema="EXA_STATISTICS",
        table="EXA_SQL_LAST_DAY",
        required_columns=(
            "SESSION_ID",
            "STMT_ID",
            "COMMAND_NAME",
            "COMMAND_CLASS",
            "DURATION",
            "START_TIME",
            "STOP_TIME",
            "CPU",
            "TEMP_DB_RAM_PEAK",
            "LOCAL_READ_SIZE",
            "REMOTE_READ_SIZE",
            "NET",
            "SUCCESS",
            "ERROR_CODE",
            "ERROR_TEXT",
            "ROW_COUNT",
            "CLUSTER_NAME",
        ),
    ),
    SourceSpec(
        id="EXA_MONITOR_LAST_DAY",
        schema="EXA_STATISTICS",
        table="EXA_MONITOR_LAST_DAY",
        required_columns=(
            "CLUSTER_NAME",
            "MEASURE_TIME",
            "LOAD",
            "CPU",
            "TEMP_DB_RAM",
            "PERSISTENT_DB_RAM",
            "NET",
            "SWAP",
        ),
    ),
    SourceSpec(
        id="EXA_SQL_DAILY",
        schema="EXA_STATISTICS",
        table="EXA_SQL_DAILY",
        required_columns=("CLUSTER_NAME", "INTERVAL_START", "COMMAND_NAME", "COMMAND_CLASS", "SUCCESS", "COUNT", "DURATION_AVG"),
    ),
    SourceSpec(
        id="EXA_MONITOR_DAILY",
        schema="EXA_STATISTICS",
        table="EXA_MONITOR_DAILY",
        required_columns=("CLUSTER_NAME", "INTERVAL_START", "CPU_AVG", "TEMP_DB_RAM_AVG", "NET_AVG", "SWAP_AVG"),
    ),
    SourceSpec(
        id="EXA_DB_SIZE_DAILY",
        schema="EXA_STATISTICS",
        table="EXA_DB_SIZE_DAILY",
        required_columns=(
            "CLUSTER_NAME",
            "INTERVAL_START",
            "STORAGE_SIZE_AVG",
            "STORAGE_SIZE_MAX",
            "USE_AVG",
            "USE_MAX",
            "RECOMMENDED_DB_RAM_SIZE_AVG",
            "OBJECT_COUNT_AVG",
        ),
    ),
    SourceSpec(
        id="EXA_USAGE_LAST_DAY",
        schema="EXA_STATISTICS",
        table="EXA_USAGE_LAST_DAY",
        required_columns=("CLUSTER_NAME", "MEASURE_TIME", "USERS", "QUERIES"),
    ),
    SourceSpec(
        id="EXA_SYSTEM_EVENTS",
        schema="EXA_STATISTICS",
        table="EXA_SYSTEM_EVENTS",
        required_columns=("CLUSTER_NAME", "MEASURE_TIME", "EVENT_TYPE", "DBMS_VERSION", "NODES", "DB_RAM_SIZE", "VCPU"),
    ),
    SourceSpec(
        id="EXA_DBA_PROFILE_LAST_DAY",
        schema="EXA_STATISTICS",
        table="EXA_DBA_PROFILE_LAST_DAY",
        required_columns=(
            "SESSION_ID",
            "STMT_ID",
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
            "NET",
        ),
    ),
    SourceSpec(
        id="EXA_DBA_PROFILE_RUNNING",
        schema="EXA_STATISTICS",
        table="EXA_DBA_PROFILE_RUNNING",
        required_columns=(
            "SESSION_ID",
            "STMT_ID",
            "PART_ID",
            "PART_NAME",
            "PART_INFO",
            "PART_FINISHED",
            "OBJECT_SCHEMA",
            "OBJECT_NAME",
            "OBJECT_ROWS",
            "OUT_ROWS",
            "DURATION",
            "CPU",
            "TEMP_DB_RAM_PEAK",
            "NET",
        ),
        privilege_required="SELECT ANY DICTIONARY",
    ),
    SourceSpec(
        id="EXA_DBA_AUDIT_SQL",
        schema="EXA_STATISTICS",
        table="EXA_DBA_AUDIT_SQL",
        required_columns=(
            "SESSION_ID",
            "STMT_ID",
            "COMMAND_NAME",
            "DURATION",
            "START_TIME",
            "STOP_TIME",
            "SUCCESS",
            "ERROR_CODE",
        ),
        privilege_required="SELECT ANY DICTIONARY + auditing enabled in EXAoperation",
    ),
    SourceSpec(
        id="EXA_DBA_SESSIONS_LAST_DAY",
        schema="EXA_STATISTICS",
        table="EXA_DBA_SESSIONS_LAST_DAY",
        required_columns=(
            "SESSION_ID",
            "LOGIN_TIME",
            "LOGOUT_TIME",
            "USER_NAME",
            "HOST",
            "SUCCESS",
            "ERROR_CODE",
            "ERROR_TEXT",
            "CLUSTER_NAME",
        ),
        privilege_required="SELECT ANY DICTIONARY",
    ),
    SourceSpec(
        id="EXA_DBA_TRANSACTION_CONFLICTS",
        schema="EXA_STATISTICS",
        table="EXA_DBA_TRANSACTION_CONFLICTS",
        required_columns=(
            "SESSION_ID",
            "CONFLICT_SESSION_ID",
            "START_TIME",
            "STOP_TIME",
            "CONFLICT_TYPE",
        ),
        privilege_required="SELECT ANY DICTIONARY",
    ),
)

# Derived diagnostics that depend solely on $EXA_* internal tables and are
# therefore permanently unavailable under this build's policy decision.
# Reported explicitly (not silently omitted) -- see docs/internal-interface-policy.md.
EXCLUDED_INTERNAL_DERIVED_CAPABILITIES: tuple[str, ...] = (
    "IN_ROWS_OUT_ROWS_ANALYSIS",
    "NODE_SYNC_ANALYSIS",
    "PROCESS_SKEW_ANALYSIS",
)
