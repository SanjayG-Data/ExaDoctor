# Security and privacy posture

## Read-only, structurally

`exadoctor.connection.gateway.ReadOnlyGateway.execute()` validates every
statement before it reaches Exasol (`validate_select_only`):

- Must start with `SELECT` or `WITH` (comments stripped first, so a
  comment hiding a different leading keyword doesn't slip through).
- Must be a single statement — a trailing `;` is allowed, but a `;`
  anywhere else (e.g. `SELECT 1; DROP TABLE x`) is rejected, including
  when hidden after a `/* comment */`.
- Anything else (`CREATE`, `ALTER`, `DROP`, `INSERT`, `UPDATE`, `DELETE`,
  `MERGE`, `KILL`, `GRANT`, `REVOKE`, `TRUNCATE`, empty input) raises
  `NonReadOnlyStatementError` before any network call is made.

No code path in this codebase constructs SQL any other way — every
collector, the capability prober, the profile collector, and the query
analyzer's targeted lookups all go through this same gateway.

## Credentials

- Read from `EXADOCTOR_HOST`/`EXADOCTOR_USER`/`EXADOCTOR_PASSWORD`
  environment variables only. Never a CLI flag (would leak into shell
  history and process listings) and never a config file.
- `ConnectionConfig.__repr__` always prints `password='***'` — a config
  object can be logged, printed in a traceback, or included in an error
  message without leaking the password.
- Connection failures are wrapped (`ConnectionFailedError`) with a message
  built from `pyexasol`'s own error object, which does not include the
  password — verified live against a real Exasol instance.
- `Snapshot`'s `DatabaseInfo` has exactly three fields: `host`, `port`,
  `version`. There is no field a password could occupy — a `Snapshot`
  (and therefore anything derived from it: `scan --format json`, a saved
  baseline, an anonymized report) is structurally incapable of holding a
  credential, not just conventionally expected not to.

## TLS

Encryption is on by default (`EXADOCTOR_ENCRYPTION=true`). Certificate
verification is also on by default; `EXADOCTOR_TLS_INSECURE=true` disables
it, and is meant only for a known local/dev instance with a self-signed
certificate (e.g. Exasol Docker-DB) — never set this against a real
deployment target.

## Sensitive data in output

- `Snapshot`, `Finding`, and the terminal/JSON/HTML reports never include
  the connecting user's password, by construction (see above).
- Raw `SQL_TEXT` is not collected by any of the twelve public collectors,
  the profile collector, or the query analyzer's workload lookup — none of
  their column lists include it, even though several source tables
  (`EXA_DBA_SESSIONS`, `EXA_DBA_PROFILE_LAST_DAY`, `EXA_DBA_PROFILE_
  RUNNING`) do carry a `SQL_TEXT` column. (An independent code review
  caught a real regression here: `profile/collector.py` briefly *did*
  select and serialize `SQL_TEXT` -- contradicting this exact claim, and
  tested to do so by its own unit test -- because it was nowhere actually
  displayed or used by any rule. Removed rather than redocumented, since
  nothing required it.)
- `--anonymize` (on `scan`) replaces `DatabaseInfo.host`, every
  `user_name`/`host` field (`SessionInfo`, `SessionHistoryRecord`), every
  `cluster_name` field, and `TransactionConflict.conflict_objects` with a
  stable pseudonym, applied *before* rules run — so rule-generated text
  (e.g. `SESSION-LONG-001`/`SESSION-AUTH-FAIL-001`'s summaries, which embed
  a username) is already pseudonymized rather than needing an unreliable
  find-and-replace pass afterward.
  - **Found and fixed by independent code review**: three `Snapshot`
    fields added after the anonymizer was first written
    (`session_history`, `sql_daily`, `monitor_daily`, `system_events`)
    were never wired into it, so `--anonymize` silently leaked real
    usernames/IP addresses/cluster names through those sources until this
    was caught and fixed (see `anonymizer.py`'s module docstring and
    `IMPLEMENTATION_HISTORY.md`). Any future `Snapshot` field carrying a
    user/host/cluster/schema/table value must be added to the anonymizer
    in the same change that adds the field, not as a follow-up.
  - **Known limitation**: free-text fields (`SqlStatement.error_text`,
    `SessionHistoryRecord.error_text`, `TransactionConflict.conflict_info`,
    `Evidence.context`) are not scrubbed — Exasol error messages can embed
    identity fragments (e.g. a table or user name), and there is no
    reliable way to redact those by string-scanning without either missing
    real values (different casing/quoting) or corrupting unrelated text.
    Treat an anonymized report's error text as still potentially sensitive
    and review it before sharing.
- The AI explanation layer (`--explain`) only ever receives a compact
  subset of `Finding` fields (id/status/title/summary/recommendation) —
  never database access, never raw evidence/limitations/documentation, and
  never credentials.
  - **Residual risk, not currently mitigated**: `Finding.summary` for
    `SQL-FAIL-001` embeds Exasol's verbatim `ERROR_TEXT`, which can contain
    arbitrary object/column identifiers chosen by any user with ordinary
    query access (confirmed live: `object ROOT_NAME not found`). Since the
    local model's system prompt tells it to "treat every field as ground
    truth," a user could in principle craft an identifier designed to read
    as an instruction to that model. Impact is bounded by the same
    architectural separation described above (the AI's output never
    reaches the deterministic report, never alters a `Finding`, and never
    executes anything) — but this is a real, currently unfiltered input
    path, flagged by an independent code review and not yet addressed.

## Anonymization gap: `exadoctor query`

`--anonymize` exists only on `scan`. `anonymize_snapshot` operates on
`Snapshot`; `exadoctor query` produces a different object (`QueryAnalysis`)
that isn't covered. Treat `exadoctor query`'s output (in any format) as
containing whatever identity the connected instance's data naturally
carries — session/statement identifiers, and any object/column names that
appear in profile parts or error text — and review before sharing it
outside your own investigation.

## No automatic remediation

Nothing in this codebase kills a session, modifies a parameter, enables
profiling/auditing, or otherwise mutates database state. `exadoctor` reads
evidence and reports findings; every recommendation is text for a human to
act on, never something the tool executes itself.
