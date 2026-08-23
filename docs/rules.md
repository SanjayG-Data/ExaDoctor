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
| `capabilities` | Probes existence/access on every registered public source (`exadoctor.capabilities.sources.PUBLIC_SOURCES`) — 12 tables in total, listed in [`capability-matrix.md`](capability-matrix.md). Most of these are checked for availability only; not all are actually collected elsewhere. |
| `scan` | `EXA_METADATA`, `EXA_PARAMETERS`, `EXA_ALL_SESSIONS`, `EXA_SQL_LAST_DAY`, `EXA_MONITOR_LAST_DAY`, `EXA_DB_SIZE_DAILY`, `EXA_USAGE_LAST_DAY` — one collector each, see `exadoctor.models.snapshot.build_snapshot`. |
| `baseline create`/`compare`/`history` | Same collection as `scan` (`build_snapshot` is reused), but `compare`/`history` only ever diff three of those fields: workload duration by class and TEMP usage (both from `EXA_SQL_LAST_DAY`) and storage size (from `EXA_DB_SIZE_DAILY`). The rest of the snapshot is saved to the local baseline store but not compared. |
| `query` | `EXA_SQL_LAST_DAY` (that one statement's own row) plus `EXA_DBA_PROFILE_LAST_DAY`/`EXA_DBA_PROFILE_RUNNING` (its profile parts, whichever source actually has rows for that session/statement). |

Two sources registered for `capabilities` are **not** read by anything
else in this build: `EXA_DBA_SESSIONS` (probed for the "enhanced,
cross-user session detail" capability, but no collector queries it —
`EXA_ALL_SESSIONS` is what `scan` actually uses) and `EXA_DBA_AUDIT_SQL`/
`EXA_DBA_TRANSACTION_CONFLICTS` (probed for future use; no current rule
or collector consumes either). `exadoctor capabilities` reports all three
as available or not, but a "yes" for them doesn't mean any other command
will use them yet.

## `exadoctor scan` — public-core rules

| Rule | Source | Evaluation |
|---|---|---|
| `SYS-SWAP-001` | `EXA_MONITOR_LAST_DAY` | Any `SWAP > 0` sample; reports the peak and how many of the window's samples were affected. Cannot identify which node — `SWAP` is a cluster-maximum-style metric. |
| `SQL-FAIL-001` | `EXA_SQL_LAST_DAY` | Groups failed statements by `(error_code, error_text, command_name)`. `WARNING` at or above the recurrence threshold (policy), `INFO` below it — an isolated failure may be ordinary user/application error. Capped per run, with an explicit "N more not shown" note if truncated. |
| `SQL-SLOW-001` | `EXA_SQL_LAST_DAY` | Per `command_class`, flags statements whose duration exceeds a policy-defined multiple of that class's own median — never a fixed-seconds threshold, since duration distributions differ wildly by class. Requires a policy-defined minimum sample count per class. |
| `SQL-TEMP-001` | `EXA_SQL_LAST_DAY` | Same median-relative approach as `SQL-SLOW-001`, applied to `TEMP_DB_RAM_PEAK` across TEMP-using statements. Its `recommendation` explicitly notes that TEMP spillover for large sorts/joins/aggregations is expected Exasol behavior, not inherently a fault, and points at `SYS-RAM-SIZING-001` before assuming a per-query problem. |
| `SQL-REMOTE-001` | `EXA_SQL_LAST_DAY` | Reports the top contributors to remote-storage reads. Always `INFO`, never auto-escalated — remote storage use can be a deliberate, expected part of a workload. |
| `SYS-TEMP-001` | `EXA_MONITOR_LAST_DAY` | Two independent checks against the window's own `TEMP_DB_RAM` median: a spike check (any sample far above median) and a sustained-elevation check (a policy-defined fraction of samples above a lower multiple). Separate findings, since a brief spike and persistent pressure call for different follow-up. Same "check `SYS-RAM-SIZING-001` before assuming a per-query problem" framing as `SQL-TEMP-001`. |
| `STORAGE-GROWTH-001` | `EXA_DB_SIZE_DAILY` | Compares the latest daily `STORAGE_SIZE_AVG` to the trailing-history median; flags growth beyond a policy-defined ratio. Trend-relative to the instance's own history, not an absolute capacity judgement. |
| `SYS-RAM-SIZING-001` | `EXA_DB_SIZE_DAILY` | Reports Exasol's own `RECOMMENDED_DB_RAM_SIZE_AVG` for the latest day — the column Exasol's [sizing documentation](https://docs.exasol.com/db/latest/administration/on-premise/sizing.htm) itself names as the way to check DB RAM sizing on a running system, and whose formula already bakes in TEMP headroom. Always `INFO`: ExaDoctor has no public source exposing the cluster's actually-provisioned RAM, so it can surface Exasol's recommendation but can't itself judge whether it's being met. |
| `SESSION-LONG-001` | `EXA_ALL_SESSIONS` + `Snapshot.database_time` | Session age = `database_time - LOGIN_TIME`, using the Exasol server's own clock (never the collecting host's — see `docs/architecture.md` for why that distinction is load-bearing). `NOT_EVALUATED` if `database_time` couldn't be determined, rather than silently using the wrong clock. |

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
