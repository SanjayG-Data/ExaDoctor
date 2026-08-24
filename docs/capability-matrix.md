# Capability matrix

Verified live against a real Exasol instance on 2026-08-22. Observed
database: `EXASolution 2026.1.0`. Connected as `SYS` for this probe (broad
privileges) — a typical deployment will run with far fewer grants, so
privilege-dependent sources below must still be treated as *possibly
unavailable* at runtime and re-probed per connection (`exadoctor
capabilities` does exactly that).

Scope: **public sources only**. `$EXA_*` internal diagnostic tables are
explicitly out of scope for this build — see
[`internal-interface-policy.md`](internal-interface-policy.md).

## Metadata schema (`SYS`)

| Source | Exists | Columns confirmed | Row access | Notes |
|---|---|---|---|---|
| `EXA_METADATA` | Yes | `PARAM_NAME`, `PARAM_VALUE`, `IS_STATIC` | OK (4 rows) | Used to resolve `databaseProductVersion` = `2026.1.0`, `databaseProductName` = `EXASolution`. |
| `EXA_PARAMETERS` | Yes | `PARAMETER_NAME`, `SESSION_VALUE`, `SYSTEM_VALUE` | OK (30 rows) | No `IS_STATIC`-style classification column. |
| `EXA_ALL_SESSIONS` | Yes | `SESSION_ID`, `USER_NAME`, `STATUS`, `COMMAND_NAME`, `STMT_ID`, `DURATION`, `QUERY_TIMEOUT`, `ACTIVITY`, `TEMP_DB_RAM`, `PERSISTENT_DB_RAM`, `LOGIN_TIME`, `CLIENT`, `DRIVER`, `ENCRYPTED`, `CONSUMER_GROUP`, `NICE`, `RESOURCES`, `CLUSTER_NAME` | OK (4 rows) | No `SQL_TEXT` column. `DURATION` is `VARCHAR`, not numeric — the collector casts it. |
| `EXA_DBA_SESSIONS` | Yes | All `EXA_ALL_SESSIONS` columns plus `EFFECTIVE_USER`, `HOST`, `OS_USER`, `OS_NAME`, `SCOPE_SCHEMA`, `SQL_TEXT` (`VARCHAR(2000000)`) | OK (4 rows) as `SYS`; requires `SELECT ANY DICTIONARY` for non-privileged users | Exposes raw `SQL_TEXT` — excluded from every collector's column list by design; see [`security.md`](security.md). |

## Statistics schema (`EXA_STATISTICS`)

| Source | Exists | Columns confirmed | Row access | Notes |
|---|---|---|---|---|
| `EXA_SQL_LAST_DAY` | Yes | 34 columns incl. `SESSION_ID`, `STMT_ID`, `COMMAND_NAME`, `COMMAND_CLASS`, `DURATION`, `START_TIME`, `STOP_TIME`, `CPU`, `TEMP_DB_RAM_PEAK`, `*_READ_SIZE`/`*_WRITE_SIZE`/`*_DURATION` (local/cache/remote), `NET`, `SUCCESS`, `ERROR_CODE`, `ERROR_TEXT`, `ROW_COUNT`, `CLUSTER_NAME` | OK (50 rows) | No detailed SQL text, no user identity. Basis for `SQL-FAIL-001`, `SQL-SLOW-001`, `SQL-TEMP-001`, `SQL-REMOTE-001`. |
| `EXA_MONITOR_LAST_DAY` | Yes | `CLUSTER_NAME`, `MEASURE_TIME`, `LOAD`, `CPU`, `TEMP_DB_RAM`, `PERSISTENT_DB_RAM`, I/O columns, `NET`, `SWAP` | OK (1053 rows) | `SWAP` column present and numeric — basis for `SYS-SWAP-001`. Cluster-maximum semantics; does not identify which node. |
| `EXA_MONITOR_DAILY` | Yes | `CLUSTER_NAME`, `INTERVAL_START`, `CPU_AVG`/`MAX`, `TEMP_DB_RAM_AVG`/`MAX`, `PERSISTENT_DB_RAM_AVG`/`MAX`, I/O columns, `NET_AVG`/`MAX`, `SWAP_AVG`/`MAX` (same metric family as `EXA_MONITOR_LAST_DAY`, pre-aggregated per day) | OK (53 rows spanning ~3 months on the probed instance) | Accumulates indefinitely like `EXA_DB_SIZE_DAILY` — the collector windows it to 90 days. Only 4 of its ~40 columns (`CPU_AVG`, `TEMP_DB_RAM_AVG`, `NET_AVG`, `SWAP_AVG`) are actually selected. Basis for `SYS-RESOURCE-TREND-001` — the first rule here to use a `_DAILY`/`_MONTHLY` variant of a metric family instead of only its `_LAST_DAY` one; see `IMPLEMENTATION_HISTORY.md` for the audit that surfaced this gap. |
| `EXA_DB_SIZE_DAILY` | Yes | `CLUSTER_NAME`, `INTERVAL_START`, `RAW_OBJECT_SIZE_*`, `MEM_OBJECT_SIZE_*`, `AUXILIARY_SIZE_*`, `STATISTICS_SIZE_*`, `RECOMMENDED_DB_RAM_SIZE_*`, `STORAGE_SIZE_*`, `USE_*`, `TEMP_VOLUME_SIZE_*`, `OBJECT_COUNT_*` | OK (51 rows) | Both AVG and MAX variants present — basis for trend-based `STORAGE-GROWTH-001`. |
| `EXA_USAGE_LAST_DAY` | Yes | `CLUSTER_NAME`, `MEASURE_TIME`, `USERS`, `QUERIES` | OK (167 rows) | Minimal. |
| `EXA_DBA_PROFILE_LAST_DAY` | Yes | `SESSION_ID`, `STMT_ID`, `COMMAND_NAME`, `COMMAND_CLASS`, `PART_ID`, `PART_NAME`, `PART_INFO`, `OBJECT_SCHEMA`, `OBJECT_NAME`, `OBJECT_ROWS`, `OUT_ROWS`, `DURATION`, `CPU`, memory/I/O columns, `NET`, `REMARKS`, `SQL_TEXT` | OK (1 row observed — profiling not broadly enabled on the probed instance) | **No `IN_ROWS` column.** Only `OUT_ROWS`, `OBJECT_ROWS`. Row-expansion analysis (`IN_ROWS`→`OUT_ROWS`) is therefore provably unavailable on the public path — see [`internal-interface-policy.md`](internal-interface-policy.md). |
| `EXA_DBA_PROFILE_RUNNING` | Yes | Same shape as `LAST_DAY` plus `PART_FINISHED` | OK (4 rows); requires `SELECT ANY DICTIONARY` | Live/running variant. |
| `EXA_DBA_AUDIT_SQL` | Yes | Same shape as `EXA_SQL_LAST_DAY` plus `SCOPE_SCHEMA`, `SQL_TEXT` | OK (274,362 rows) | Populated only when auditing is enabled in EXAoperation — do not assume availability. |
| `EXA_DBA_TRANSACTION_CONFLICTS` | Yes | `SESSION_ID`, `CONFLICT_SESSION_ID`, `START_TIME`, `STOP_TIME`, `CONFLICT_TYPE`, `CONFLICT_OBJECTS`, `CONFLICT_INFO` | OK (5,102 rows) | Requires `SELECT ANY DICTIONARY`. `STOP_TIME` is `NULL` for a conflict still open at query time. `CONFLICT_TYPE` documented values: `WAIT FOR COMMIT`, `TRANSACTION ROLLBACK`. Basis for `SQL-CONFLICT-001`. Accumulates indefinitely like `EXA_DB_SIZE_DAILY` — the collector windows it to the last day. |
| `EXA_SYSTEM_EVENTS` | Yes | `CLUSTER_NAME`, `MEASURE_TIME`, `EVENT_TYPE` (`STARTUP`/`SHUTDOWN`/`RESTART`/backup/recovery events), `DBMS_VERSION`, `NODES`, `DB_RAM_SIZE` ("Used DB RAM license in GiB", per Exasol's own column comment), `PARAMETERS`, `VCPU` | OK (55 rows spanning since 2026-05-15 on the probed instance) | One row per lifecycle event, not a rolling telemetry stream — stays small over a cluster's realistic lifetime, no window needed. `DB_RAM_SIZE` is the actually-provisioned counterpart to `EXA_DB_SIZE_DAILY.RECOMMENDED_DB_RAM_SIZE_AVG` — basis for `SYS-RAM-SIZING-001`'s real comparison. Not `DBA_`-prefixed; confirmed readable both as `SYS` here and as a real non-`sys` Exasol SaaS user with no explicit grant observed for it, so likely open to all users, though the exact requirement (if any) is still unconfirmed. |

## Privilege note

`CURRENT_USER` for this probe resolved to `SYS`, which has implicit
superuser rights rather than granted privileges — so privilege-gated
sources (`EXA_DBA_SESSIONS`, `EXA_DBA_PROFILE_RUNNING`, `EXA_DBA_AUDIT_SQL`,
`EXA_DBA_TRANSACTION_CONFLICTS`) have not been proven against a genuinely
restricted user. `exadoctor capabilities`'s probe logic degrades a denied
source gracefully (`available=False` with a reason, same code path as a
missing table) and this is unit-tested, but re-run `exadoctor
capabilities` against your own connecting user to see what it can
actually see — don't assume this table's results transfer.

## Derived capabilities available on the public-only path

| Derived diagnostic | Status | Basis |
|---|---|---|
| Workload duration/error analysis | Available | `EXA_SQL_LAST_DAY` |
| System pressure / swap detection | Available | `EXA_MONITOR_LAST_DAY` |
| Multi-day resource usage trend (CPU/TEMP DB RAM/network/swap) | Available | `EXA_MONITOR_DAILY` (`SYS-RESOURCE-TREND-001`) |
| Capacity/growth trend | Available | `EXA_DB_SIZE_DAILY` |
| Session inspection (basic) | Available | `EXA_ALL_SESSIONS` |
| Session inspection (enhanced, cross-user) | Privilege-dependent | `EXA_DBA_SESSIONS` |
| Completed query profile (part-level, no `IN_ROWS`) | Available when profiling enabled | `EXA_DBA_PROFILE_LAST_DAY` |
| Running query profile | Privilege-dependent | `EXA_DBA_PROFILE_RUNNING` |
| IN_ROWS / OUT_ROWS row-expansion analysis | **NOT_EVALUATED by design** | No public source carries `IN_ROWS`; internal-only, out of scope |
| NODE SYNC analysis | **NOT_EVALUATED by design** | Internal-only, out of scope |
| Per-process imbalance / skew | **NOT_EVALUATED by design** | Internal-only, out of scope |
| Audit SQL analysis | Conditional | `EXA_DBA_AUDIT_SQL`, requires auditing enabled |
| Transaction conflict analysis | Available (privilege-dependent) | `EXA_DBA_TRANSACTION_CONFLICTS` (`SQL-CONFLICT-001`) |
| DB RAM sizing vs. Exasol's own recommendation | Available | `EXA_DB_SIZE_DAILY` + `EXA_SYSTEM_EVENTS` (`SYS-RAM-SIZING-001`) |
