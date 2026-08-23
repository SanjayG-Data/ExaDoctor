<div align="center">

<img src="assets/logo.svg" width="96" height="96" alt="ExaDoctor logo">

# ExaDoctor

### Read-only diagnostics for Exasol.

**No writes. No invented diagnoses. No black box.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![Database access: read-only](https://img.shields.io/badge/database%20access-read--only-brightgreen)](docs/security.md)
[![For Exasol](https://img.shields.io/badge/for-Exasol-1a1a1a)](https://www.exasol.com/)

```sh
curl -fsSL https://raw.githubusercontent.com/SanjayG-Data/ExaDoctor/main/install.sh | sh
```

</div>

---

## What is this?

ExaDoctor is a command-line tool that checks an Exasol database for
common health and performance issues — repeated SQL errors, slow or
memory-heavy statements, swap activity, unusual storage growth,
long-lived sessions — and reports each one with the actual evidence
behind it, not just an alert.

Every query it runs is a single read-only `SELECT`/`WITH` statement,
enforced structurally, not by convention. If the evidence a finding
needs isn't available, it says so instead of guessing.

## Quick start

```sh
# 1. install
curl -fsSL https://raw.githubusercontent.com/SanjayG-Data/ExaDoctor/main/install.sh | sh

# 2. point it at your database
export EXADOCTOR_HOST=localhost
export EXADOCTOR_USER=sys
export EXADOCTOR_PASSWORD=...

# 3. run it
exadoctor scan
```

*(Windows PowerShell? `export` won't work there — see
[Configure](#configure) below for the `$env:` equivalent.)*

### Requirements

- A reachable Exasol instance.
- Nothing else — the installer takes care of any Python setup for you.

## All commands

```
exadoctor capabilities             probe what this instance will let you diagnose
exadoctor scan                     full health scan, reported as findings + evidence
exadoctor query SESSION_ID STMT_ID deep root-cause analysis for one statement
exadoctor baseline create NAME     save a named snapshot for later comparison
exadoctor baseline compare NAME    diff a fresh snapshot against a saved one
exadoctor baseline history NAME    trend across every saved version of NAME
exadoctor baseline list            list every saved baseline
exadoctor --help                   full option reference for any command
```

Add `--explain` to `scan` or `query` for an optional plain-language AI
summary of the findings (needs a local LLM configured — see
[Configure](#configure)); every finding is already a complete,
evidence-backed diagnosis without it.

## Configure

Connection settings are environment variables only — never CLI flags
(which would leak into shell history) and never a config file:

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `EXADOCTOR_HOST` | yes | — | Exasol host |
| `EXADOCTOR_USER` | yes | — | Username |
| `EXADOCTOR_PASSWORD` | yes | — | Password |
| `EXADOCTOR_PORT` | no | `8563` | Port |
| `EXADOCTOR_SCHEMA` | no | none | Schema to open on connect |
| `EXADOCTOR_ENCRYPTION` | no | `true` | TLS on/off |
| `EXADOCTOR_TLS_INSECURE` | no | `false` | Skip TLS cert verification — only for a known local/dev instance with a self-signed cert (e.g. Exasol Docker-DB); never for a real deployment |
| `EXADOCTOR_BASELINE_DB` | no | `~/.exadoctor/baselines.db` | Local SQLite path for `baseline` |
| `EXADOCTOR_LLM_PROVIDER` | no | `none` | Set to `local` to enable `--explain` |
| `EXADOCTOR_LLM_BASE_URL` | no | `http://localhost:8080` | Local LLM server (OpenAI-compatible `/v1/chat/completions`, e.g. a llama.cpp server) |

**Setting these — macOS/Linux/WSL (bash/zsh):**

```sh
export EXADOCTOR_HOST=localhost
export EXADOCTOR_USER=sys
export EXADOCTOR_PASSWORD=...
```

**Windows (PowerShell)** — `export` doesn't exist there; use `$env:` instead:

```powershell
$env:EXADOCTOR_HOST = "localhost"
$env:EXADOCTOR_USER = "sys"
$env:EXADOCTOR_PASSWORD = "..."
```

Either way, these only last for the current terminal session — set them
again in each new window, or add them to your shell profile
(`~/.bashrc`/`~/.zshrc`, or PowerShell's `$PROFILE`) to persist them.

**What user should I connect as?** Any user with ordinary query access
works — ExaDoctor never needs `CREATE`/`ALTER`/`GRANT` or any other write
privilege, so a dedicated read-only monitoring user is a good fit. A few
things are more useful with `SELECT ANY DICTIONARY` granted (cross-user
session detail, and `query`'s live-profile lookup), but nothing breaks
without it — run `exadoctor capabilities` after connecting to see exactly
what your user can and can't see.

## Command details

### `exadoctor capabilities`

Probes which sources are actually available and readable on the
connected instance — run this first on a new instance to see what
ExaDoctor will (and won't) be able to diagnose there, before staring at
`scan` output wondering why something is missing.

```
$ exadoctor capabilities
EXADOCTOR CAPABILITY REPORT

Database version: 2026.1.0

PUBLIC SOURCES
  EXA_METADATA                 AVAILABLE (data present)
  EXA_ALL_SESSIONS             AVAILABLE (data present)
  EXA_SQL_LAST_DAY             AVAILABLE (data present)
  EXA_MONITOR_LAST_DAY         AVAILABLE (data present)
  EXA_DB_SIZE_DAILY            AVAILABLE (data present)
  EXA_DBA_PROFILE_LAST_DAY     AVAILABLE (no rows in window)
  ...
```

A source reading `AVAILABLE (no rows in window)` isn't an error — it means
ExaDoctor can see the table but there's nothing in it right now (e.g.
profiling not enabled, or no activity yet). `--format json` is also
available.

### `exadoctor scan`

The main command: a full health scan, reported as a list of findings,
each carrying the evidence that produced it.

```
$ exadoctor scan
EXADOCTOR SCAN REPORT

Database: 2026.1.0 @ localhost:8564
Collected: 2026-08-23T07:07:31Z
...

[WARNING] SQL-FAIL-001 - Repeated SQL errors
    6 occurrence(s) across 2 session(s) of SELECT failing with error_code='42000': object SOME_TABLE not found
    recommendation: Investigate this recurring failure; it affects multiple sessions/statements and may be systemic.
    evidence: ERROR_COUNT=6 occurrences at 2026-08-22T16:19:50 [EXA_SQL_LAST_DAY]
    limitation: EXA_SQL_LAST_DAY does not expose user identity or full SQL text, only COMMAND_NAME/ERROR_CODE/ERROR_TEXT.
```

Every finding is `PASS`, `INFO`, `WARNING`, or `NOT_EVALUATED` — never a
diagnosis invented from missing data.

| Flag | Purpose |
|---|---|
| `--format [text\|json\|html]` | Output format. `html` produces one self-contained file you can open in a browser or attach to a ticket. |
| `--output PATH` | Write the report to a file instead of stdout. |
| `--anonymize` | Replace host/username/cluster-name values with stable pseudonyms before reporting, so you can share output externally (e.g. with a vendor's support team) without exposing your environment's identity. Free-text error messages aren't scrubbed — review before sharing. |
| `--explain` | Add a plain-language AI summary of the findings from a local LLM (needs `EXADOCTOR_LLM_PROVIDER=local`). |

```sh
exadoctor scan --format json --output scan.json
exadoctor scan --format html --output report.html
exadoctor scan --anonymize
```

### `exadoctor query SESSION_ID STMT_ID`

Deep root-cause analysis for one specific statement, once `scan` (or your
own monitoring) has pointed you at a `SESSION_ID`/`STMT_ID` worth
investigating: its profile parts, dominant execution part, and any
findings specific to that one statement.

```
$ exadoctor query 1874233022592647168 1
EXADOCTOR QUERY ANALYSIS

Session: 1874233022592647168   Statement: 1

WORKLOAD (EXA_SQL_LAST_DAY)
  Command: SELECT (DQL)   Success: False
  Duration: 71.822s   CPU: 80.7%
  TEMP peak: 76.0 MiB   Remote read: 0.0 MiB   Rows: None

PROFILE (not available)
  Not available: no rows in EXA_DBA_PROFILE_LAST_DAY or EXA_DBA_PROFILE_RUNNING.

FINDINGS (1 total: 1 NOT_EVALUATED)

[NOT_EVALUATED] PERF-NO-PROFILE - No profile data
    No profile parts found for session 1874233022592647168, statement 1.
    limitation: Profiling may not have been enabled for this session, the statement may have completed outside the profile retention window, or the session_id/stmt_id may not exist.
```

(This particular example has no profile data because profiling wasn't
enabled on the instance it was run against — shown here deliberately,
since `NOT_EVALUATED` rather than a guess is exactly the point.)

Both `--format [text|json]` and `--explain` are available, same meaning
as on `scan`. Note: `--anonymize` is not available on `query` yet —
treat its output as containing whatever identifying detail your data
naturally carries.

### `exadoctor baseline`

Save a named snapshot locally and track how things change over time,
without needing a separate monitoring system.

```sh
exadoctor baseline create production      # save today's snapshot as "production"
exadoctor baseline list                   # see every saved baseline
exadoctor baseline compare production     # collect a fresh snapshot, diff it against the saved one
exadoctor baseline history production     # trend across every saved version of "production"
```

`compare` output:

```
$ exadoctor baseline compare production
EXADOCTOR BASELINE COMPARISON

Baseline collected: 2026-08-23T07:07:55Z
Current collected:  2026-08-23T07:07:58Z

WORKLOAD DURATION (median seconds, by command class)
  workload duration (DQL): 0.021 -> 0.021 seconds (+0.000 seconds, +0.0%) [n=2740 -> 2740]
  workload duration (TRANSACTION): 0.001 -> 0.001 seconds (+0.000 seconds, +0.0%) [n=2709 -> 2709]

TEMP USAGE (median MiB)
  TEMP usage (median): 34.900 -> 34.900 MiB (+0.000 MiB, +0.0%) [n=5452 -> 5904]
```

A command class with too few samples in either snapshot is reported as
`[NOT COMPARABLE]` rather than a misleading percentage.

---

## Why you can point this at production

- **It cannot write.** Every query goes through a single gateway that
  only accepts one `SELECT`/`WITH` statement per call — anything else
  (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `KILL`, stacked statements, ...)
  is rejected before it ever reaches your database.
- **It never invents a diagnosis.** If the evidence a finding needs isn't
  available (missing privilege, feature not enabled, empty window), it's
  reported as `NOT_EVALUATED`, never guessed at as a false pass.
- **It only reads documented, public system tables** (`EXA_*`,
  `EXA_STATISTICS.*`) — never undocumented internal interfaces that could
  change without notice between Exasol versions. A small number of deep
  diagnostics (row-expansion analysis, per-process skew) are permanently
  out of scope as a result — `exadoctor capabilities` shows you exactly
  which.
- **Your credentials never appear in output.** Passwords are read from
  environment variables only, never logged, and structurally excluded
  from every report format (there's no field one could occupy).
- **Nothing runs automatically.** ExaDoctor never kills a session,
  changes a parameter, or enables a feature on your behalf — every
  recommendation is text for a human to act on.

## Quick answers

| Question | Answer |
|---|---|
| Does this ever modify my database? | No. The SQL gateway only accepts a single `SELECT`/`WITH` statement — everything else is rejected before it reaches Exasol. |
| What privileges does the connecting user need? | None beyond ordinary query access. A few checks are richer with `SELECT ANY DICTIONARY`; nothing breaks without it. |
| A source shows "no rows in window" — is that an error? | No — ExaDoctor can see the table, there's just nothing in it right now (e.g. profiling not enabled, or no recent activity). |
| Can I share a report outside my team? | Use `exadoctor scan --anonymize` first — it replaces host/username/cluster-name with stable pseudonyms. Review free-text error messages before sharing; they aren't scrubbed. |
| Do I need the AI/`--explain` feature? | No — it's optional. Every finding is already a complete, evidence-backed diagnosis without it. |
| Does it support `$EXA_*` internal tables? | No, deliberately — only documented public system tables, so results don't depend on undocumented internals that can change between versions. |
| How do I remove it? | `uv tool uninstall exadoctor` |

## Learn more

- [`docs/security.md`](docs/security.md) — full security and privacy
  posture (credential handling, TLS, what `--anonymize` does and doesn't
  cover).
- [`docs/privileges.md`](docs/privileges.md) — exactly what each source
  requires and what's lost without it.
- [`docs/rules.md`](docs/rules.md) — the full catalogue of checks
  ExaDoctor runs.
- [`docs/architecture.md`](docs/architecture.md) — internals, for anyone
  extending or auditing the tool.

---

<div align="center">

Questions or issues: open an issue in this repository.

Licensed under [MIT](LICENSE).

</div>
