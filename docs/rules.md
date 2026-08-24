# Rule catalogue

Every rule is `(Snapshot | QueryProfile, RulePolicy) -> list[Finding]` —
pure functions, no gateway access, no ability to execute SQL. Source:
`exadoctor.rules.public_core` (scan) and `exadoctor.profile.rules` (query).

Thresholds cited as "ExaDoctor policy" are this tool's own configurable
defaults (`exadoctor.rules.policy.RulePolicy`), not Exasol behavior — every
finding's `documentation` field says which kind of source backs it
(Exasol documentation vs. ExaDoctor policy), per the roadmap's requirement
to distinguish the two.

## Data sources by command

What each command actually reads — confirmed against the collector/probe
code itself, not just the registry of what's *available*
([`capability-matrix.md`](capability-matrix.md) covers that broader,
"could this be read at all" question; this is narrower: "does this
command's own code path touch it").

| Command | Tables it reads |
|---|---|
| `capabilities` | Probes existence/access on every registered public source (`exadoctor.capabilities.sources.PUBLIC_SOURCES`) — 15 tables in total, listed in [`capability-matrix.md`](capability-matrix.md). Most of these are checked for availability only; not all are actually collected elsewhere. |
| `scan` | `EXA_METADATA`, `EXA_PARAMETERS`, `EXA_ALL_SESSIONS`, `EXA_DBA_SESSIONS_LAST_DAY`, `EXA_SQL_LAST_DAY`, `EXA_MONITOR_LAST_DAY`, `EXA_MONITOR_DAILY`, `EXA_DB_SIZE_DAILY`, `EXA_USAGE_LAST_DAY`, `EXA_SYSTEM_EVENTS`, `EXA_DBA_TRANSACTION_CONFLICTS` — one collector each, see `exadoctor.models.snapshot.build_snapshot`. |
| `baseline create`/`compare`/`history` | Same collection as `scan` (`build_snapshot` is reused), but `compare`/`history` only ever diff three of those fields: workload duration by class and TEMP usage (both from `EXA_SQL_LAST_DAY`) and storage size (from `EXA_DB_SIZE_DAILY`). The rest of the snapshot is saved to the local baseline store but not compared. |
| `query` | `EXA_SQL_LAST_DAY` (that one statement's own row) plus `EXA_DBA_PROFILE_LAST_DAY`/`EXA_DBA_PROFILE_RUNNING` (its profile parts, whichever source actually has rows for that session/statement). |

One source registered for `capabilities` is **not** read by anything
else in this build: `EXA_DBA_SESSIONS` (probed for the "enhanced,
cross-user session detail" capability, but no collector queries it —
`EXA_ALL_SESSIONS` is what `scan` actually uses). `EXA_DBA_AUDIT_SQL` is
similarly probed but not yet consumed by any rule. `EXA_DBA_TRANSACTION_CONFLICTS`
*used* to be in that same "probed but unused" category — it's now read by
`SQL-CONFLICT-001` (see below).

**Exasol documents 31 statistical system tables in total** (see
[the official list](https://docs.exasol.com/db/latest/sql_references/system_tables/statistical_system_tables.htm))
— ExaDoctor uses 15 of them. Every metric family (`SQL`, `MONITOR`,
`DB_SIZE`, `USAGE`) also has `_HOURLY`/`_DAILY`/`_MONTHLY` variants beyond
the `_LAST_DAY` one this project used almost exclusively at first;
`EXA_MONITOR_DAILY` (used by `SYS-RESOURCE-TREND-001` below) was the
first of those to get used. Real session *history* (`EXA_DBA_SESSIONS_LAST_DAY`
— includes closed/failed logins, unlike the currently-open-only
`EXA_ALL_SESSIONS`) is now used too, by `SESSION-AUTH-FAIL-001` and
`SESSION-TERMINATED-001` below. Impersonation tracking
(`EXA_DBA_AUDIT_IMPERSONATION`/`EXA_DBA_IMPERSONATION_LAST_DAY`) remains
unexplored — see `IMPLEMENTATION_HISTORY.md` for the full audit.

## `exadoctor scan` — public-core rules

| Rule | Source | Evaluation |
|---|---|---|
| `SYS-SWAP-001` | `EXA_MONITOR_LAST_DAY` | Any `SWAP > 0` sample; reports the peak and how many of the window's samples were affected. Cannot identify which node — `SWAP` is a cluster-maximum-style metric. |
| `SQL-FAIL-001` | `EXA_SQL_LAST_DAY` | Groups failed statements by `(error_code, error_text, command_name)`. `WARNING` at or above the recurrence threshold (policy), `INFO` below it — an isolated failure may be ordinary user/application error. Capped per run, with an explicit "N more not shown" note if truncated. |
| `SQL-SLOW-001` | `EXA_SQL_LAST_DAY` | Per `command_class`, flags statements whose duration exceeds a policy-defined multiple of that class's own median — never a fixed-seconds threshold, since duration distributions differ wildly by class. Requires a policy-defined minimum sample count per class. |
| `SQL-TEMP-001` | `EXA_SQL_LAST_DAY` | Same median-relative approach as `SQL-SLOW-001`, applied to `TEMP_DB_RAM_PEAK` across TEMP-using statements. Its `recommendation` explicitly notes that TEMP spillover for large sorts/joins/aggregations is expected Exasol behavior, not inherently a fault, and points at `SYS-RAM-SIZING-001` before assuming a per-query problem. |
| `SQL-REMOTE-001` | `EXA_SQL_LAST_DAY` | Reports the top contributors to remote-storage reads. Always `INFO`, never auto-escalated — remote storage use can be a deliberate, expected part of a workload. |
| `SQL-COMMAND-SHARE-001` | `EXA_SQL_LAST_DAY` | Groups by `COMMAND_NAME`, reports which command type(s) account for the largest share of total workload duration and CPU-seconds — a composition view, distinct from `SQL-SLOW-001`'s per-statement outlier detection (a command type can dominate the total without any single statement of it being an outlier). CPU share is `CPU% × DURATION` summed per group, not a naive sum of the raw `CPU` percentage column (which is an instantaneous utilization reading, not a summable magnitude — a correctness fix over the legacy tool this was adapted from). Always `INFO`, same reasoning as `SQL-REMOTE-001`. |
| `SQL-CONFLICT-001` | `EXA_DBA_TRANSACTION_CONFLICTS` + `EXA_SQL_LAST_DAY` | Sums transaction-conflict wait time (`WAIT FOR COMMIT`/`TRANSACTION ROLLBACK`, windowed to the last day) and expresses it as a share of total workload duration in the same window; `WARNING` at or above a policy-defined share threshold. A distinct bottleneck class from every other workload rule here — concurrency/lock contention between sessions, not plan or data-movement inefficiency within one statement. Requires `SELECT ANY DICTIONARY`. |
| `SYS-TEMP-001` | `EXA_MONITOR_LAST_DAY` | Two independent checks against the window's own `TEMP_DB_RAM` median: a spike check (any sample far above median) and a sustained-elevation check (a policy-defined fraction of samples above a lower multiple). Separate findings, since a brief spike and persistent pressure call for different follow-up. Same "check `SYS-RAM-SIZING-001` before assuming a per-query problem" framing as `SQL-TEMP-001`. |
| `SYS-RESOURCE-TREND-001` | `EXA_MONITOR_DAILY` | Same statistical shape as `STORAGE-GROWTH-001` (latest day vs. trailing-history median), applied independently to CPU/TEMP DB RAM/network/swap daily averages — each with its own absolute floor since the metrics aren't on comparable scales. Unlike `SYS-SWAP-001`/`SYS-TEMP-001` (only ever look at the current 24-hour window), this can see a metric trending up over weeks that a 24h-only check structurally cannot. When the trailing median is exactly zero (swap's normal baseline), the absolute floor alone decides rather than an undefined ratio. |
| `STORAGE-GROWTH-001` | `EXA_DB_SIZE_DAILY` | Compares the latest daily `STORAGE_SIZE_AVG` to the trailing-history median; flags growth beyond a policy-defined ratio. Trend-relative to the instance's own history, not an absolute capacity judgement. |
| `SYS-RAM-SIZING-001` | `EXA_DB_SIZE_DAILY` + `EXA_SYSTEM_EVENTS` | Compares Exasol's own `RECOMMENDED_DB_RAM_SIZE_AVG` (the column Exasol's [sizing documentation](https://docs.exasol.com/db/latest/administration/on-premise/sizing.htm) itself names as the way to check DB RAM sizing on a running system, and whose formula already bakes in TEMP headroom) against the cluster's actually-provisioned `DB_RAM_SIZE`. `WARNING` if provisioned RAM is below the recommendation, `PASS` if it meets or exceeds it. Falls back to `INFO` (reporting only the recommendation) if `EXA_SYSTEM_EVENTS` is unavailable. |
| `SESSION-LONG-001` | `EXA_ALL_SESSIONS` + `Snapshot.database_time` | Session age = `database_time - LOGIN_TIME`, using the Exasol server's own clock (never the collecting host's — see `docs/architecture.md` for why that distinction is load-bearing). `NOT_EVALUATED` if `database_time` couldn't be determined, rather than silently using the wrong clock. |
| `SESSION-AUTH-FAIL-001` | `EXA_DBA_SESSIONS_LAST_DAY` | Groups failed login attempts (`SUCCESS = FALSE`) by `(user_name, host)`. `WARNING` at or above a policy-defined recurrence threshold, `INFO` below it — an isolated failure may just be a typo. Invisible to any other rule here: `EXA_ALL_SESSIONS`/`EXA_DBA_SESSIONS` only ever list sessions that successfully opened, so a failed login never appears there at all. |
| `SESSION-TERMINATED-001` | `EXA_DBA_SESSIONS_LAST_DAY` | Groups sessions that logged in successfully but were forcefully terminated (`SUCCESS = TRUE` with `ERROR_CODE` set — e.g. an idle timeout) by `ERROR_CODE`. Same recurrence framing as `SQL-FAIL-001`/`SESSION-AUTH-FAIL-001`: one occurrence is routine, many with the same code suggests a systemic connection-handling issue. Also invisible elsewhere — a session that's already ended has simply disappeared from `EXA_ALL_SESSIONS`, successful termination or not. |

## `exadoctor query` — deep per-statement rules

Public-only subset of the roadmap's deep profile rules (section 8.2) —
`IN_ROWS`-based row-expansion and NODE SYNC analysis need internal `$EXA_*`
sources this build doesn't use (see `docs/internal-interface-policy.md`).

| Rule | Evaluation |
|---|---|
| `PERF-BOTTLENECK-001` | Finds the profile part with the largest share of total statement duration. `WARNING` at or above a policy-defined share threshold. A total duration of exactly `0.000s` is treated as "negligible" (`PASS`), not `NOT_EVALUATED` — that's real data (sub-millisecond, `DURATION` is `DECIMAL(12,3)`), not missing evidence. |
| `PERF-GLOBAL-001` | Reports each part whose `PART_INFO` contains `GLOBAL`, correlated with its network throughput — always `INFO`, since GLOBAL operations are a normal part of distributed execution, not inherently a problem. |
| `PERF-EXPR-INDEX-001` | Flags any part whose `PART_INFO` contains `EXPRESSION INDEX` — always `WARNING`, since building one inline is a real, avoidable cost if the index could be created ahead of time. |
| `PERF-TEMP-MATERIALIZE-001` | Finds the part with the largest `TEMP_DB_RAM_PEAK`. `WARNING` if it's marked `TEMPORARY` in `PART_INFO` or exceeds a policy threshold; `INFO` otherwise. |

**Live-verification status**: the `PART_INFO` marker vocabulary these rules
check for (`GLOBAL`, `EXPRESSION INDEX`, `TEMPORARY`) is a *subset* of
Exasol's own documented values for that column — the live column comment
also lists `NL JOIN` and `REPLICATED`, which no current rule needs and
which this is not claiming to be exhaustive about. The three markers used
here are Exasol's own documented semantics, and these rules are thoroughly
fixture-tested against them, but
have not been observed against genuinely multi-part live profile data —
the available test instance has profiling broadly disabled (only a single
`ROLLBACK` part exists there). Treat as fixture-proven, not live-proven,
until checked against a real multi-part statement.

## Severity discipline

- Prefer `INFO` when evidence is unusual but not inherently wrong.
- `WARNING` only for evidence indicating a real, actionable risk.
- Never infer a root cause from one metric alone when multiple explanations
  remain plausible — state the evidence, let the recommendation suggest
  investigation rather than a diagnosis.
- Missing or insufficient evidence is `NOT_EVALUATED`, never `PASS`.
