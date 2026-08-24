# Privileges

ExaDoctor probes each source independently and degrades gracefully when a
privilege is missing (`available=False` with a reason, same code path as a
missing table — see `exadoctor.capabilities.probe`). Nothing in this list
is required for the tool to run; it changes which findings are possible.

| Source | Privilege required | What's lost without it |
|---|---|---|
| `EXA_METADATA`, `EXA_PARAMETERS` | None (all users) | — |
| `EXA_ALL_SESSIONS` | None (all users) | — |
| `EXA_SQL_LAST_DAY`, `EXA_MONITOR_LAST_DAY`, `EXA_DB_SIZE_DAILY`, `EXA_USAGE_LAST_DAY` | None (all users) | — |
| `EXA_SYSTEM_EVENTS` | Confirmed available to a non-`sys` user on real Exasol SaaS (see below); not `DBA_`-prefixed, so likely no special grant needed, but the exact requirement (if any) is still unconfirmed | `SYS-RAM-SIZING-001`'s comparison against actually-provisioned DB RAM (falls back to reporting only Exasol's recommendation) |
| `EXA_DBA_SESSIONS` | `SELECT ANY DICTIONARY` | Cross-user session detail beyond what `EXA_ALL_SESSIONS` shows |
| `EXA_DBA_SESSIONS_LAST_DAY` | `SELECT ANY DICTIONARY` (by `DBA_`-prefix convention; see caveat below) | `SESSION-AUTH-FAIL-001` (failed login detection) and `SESSION-TERMINATED-001` (forced termination detection) — both degrade to `NOT_EVALUATED` without it |
| `EXA_DBA_PROFILE_LAST_DAY` | Privilege-dependent; also requires profiling to have been enabled for the session that ran the statement | `exadoctor query`'s completed-statement profile |
| `EXA_DBA_PROFILE_RUNNING` | `SELECT ANY DICTIONARY` | `exadoctor query`'s live/in-flight profile fallback |
| `EXA_DBA_AUDIT_SQL` | `SELECT ANY DICTIONARY`, and auditing must be enabled in EXAoperation | Not currently used by any collector or rule in this build |
| `EXA_DBA_TRANSACTION_CONFLICTS` | `SELECT ANY DICTIONARY` | `SQL-CONFLICT-001` (transaction-conflict contention) — degrades to `NOT_EVALUATED` without it |

**Verified live against both a `sys`-level connection and a real non-`sys`
Exasol SaaS user** — the SaaS role happened to have every privilege-gated
source above already granted, so that run confirms these sources work
correctly *when* granted, but doesn't yet prove the denial path (a
restricted user *without* these grants) against a live server — that
side is still only unit-tested against a simulated denied source
(`tests/unit/test_capabilities_probe.py`). Run `exadoctor capabilities`
against your own connecting user rather than assuming either result
transfers.

## What ExaDoctor never needs

No `CREATE`/`ALTER`/`GRANT` privilege of any kind — the SQL gateway rejects
every statement type except `SELECT`/`WITH` regardless of what the
connecting user is permitted to do (see `docs/security.md`).
