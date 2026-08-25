# Architecture

This describes the system as actually built.

## Pipeline

```
raw Exasol source (public EXA_*/EXA_STATISTICS.* tables only)
        |
        v
ReadOnlyGateway (SELECT/WITH-only; exadoctor.connection.gateway)
        |
        v
capability probe                    collectors
(exadoctor.capabilities)            (exadoctor.collectors)
        |                                  |
        +----------------+-----------------+
                          v
                  Snapshot (exadoctor.models.snapshot)
                          |
                          v
              rule engine (exadoctor.rules)
                          |
                          v
                  Finding[] (exadoctor.models.finding)
                          |
        +--------+--------+--------+
        v        v        v        v
     terminal   JSON    HTML    (anonymize, optional)
                                       |
                                       v
                          AI explanation (optional, local LLM)
```

Rules never see a gateway or connection — a `Rule` is `(Snapshot,
RulePolicy) -> list[Finding]`, so it is structurally incapable of executing
SQL. One rule raising degrades to a single `NOT_EVALUATED` finding; it
never aborts the run (`exadoctor.rules.engine.run_rules`). The same
independent-failure pattern is used one level down: `probe_all` and
`collect_all` never let one broken source take down the others.

## The query analyzer is a parallel, narrower pipeline

`exadoctor query SESSION_ID STMT_ID` does not go through `Snapshot` at all.
It looks up one `EXA_SQL_LAST_DAY` row and one `EXA_DBA_PROFILE_LAST_DAY`/
`EXA_DBA_PROFILE_RUNNING` profile (bounded by `SESSION_ID`/`STMT_ID`, never
a full-table scan), correlates them into a `QueryAnalysis`
(`exadoctor.profile.analyzer`), and runs a separate, smaller set of deep
per-statement rules (`exadoctor.profile.rules`) against the `QueryProfile`.

## Why `$EXA_*` never appears in this pipeline

Every collector and the capability registry (`exadoctor.capabilities.
sources.PUBLIC_SOURCES`) reference only documented, public sources. This
was a deliberate scope decision, not a temporary gap — see
`docs/internal-interface-policy.md`. The practical effect: `IN_ROWS`-based
row-expansion analysis, NODE SYNC analysis, and per-process skew are
permanently unavailable and reported as such (not silently omitted) in
`exadoctor capabilities`.

## Key correctness decisions (each found by testing against a real instance)

- **`ReadOnlyGateway` always passes `fetch_mapper=pyexasol.exasol_mapper`.**
  Without it, `pyexasol` returns raw wire-format strings for any `DECIMAL`
  with nonzero scale and for every `TIMESTAMP`/`DATE` column instead of
  `Decimal`/`datetime`/`date`. This is set once at the gateway so every
  collector gets already-normalized types for free.
- **`Snapshot.database_time` exists specifically so age-based rules never
  compare against the collecting host's clock.** Exasol `TIMESTAMP` values
  are naive (no tzinfo); comparing them against a naive `datetime.now()`
  on whatever machine runs `exadoctor` is silently wrong under any
  timezone/clock-skew mismatch with the actual Exasol server. `probe_
  database_time()` fetches the server's own `CURRENT_TIMESTAMP` (cast to
  plain `TIMESTAMP` — the raw type is `TIMESTAMP WITH LOCAL TIME ZONE`,
  which `pyexasol`'s bundled mapper does not convert) so `SESSION-LONG-001`
  and similar rules compare two timestamps from the same clock.
- **`Finding` lives in `exadoctor.models`, not `exadoctor.rules`.** It was
  originally defined alongside the rule engine, which created a genuine
  circular import once `Snapshot.findings` needed to hold typed `Finding`
  objects (`models` needed `rules`, `rules` needed `models`). Fixed by
  moving `Finding`/`Evidence` to the `models` package, since a Finding is
  a normalized model like `Snapshot`/`Capability`, not rule logic — making
  the dependency strictly one-way.
- **The `--explain` prompt sends a compact per-finding summary, not
  `Finding.to_dict()`, and caps how many findings are included.** Measured
  live against the local model this ships with: both prompt processing and
  generation run at roughly 1 token/second (CPU inference). Sending every
  finding's full evidence/limitations/documentation for an 18-finding scan
  would put prompt processing alone in the 5-10 minute range.

## Package layout

```
src/exadoctor/
  connection/    ConnectionConfig, ReadOnlyGateway (SELECT-only SQL gateway)
  capabilities/  Capability model, source registry, tiered live probing,
                 capability report
  collectors/    one bounded collector per public source -> typed rows,
                 plus orchestrator.collect_all() running them all
  models/        Snapshot, Finding/Evidence, DatabaseInfo -- the only
                 objects rules/reports ever read
  rules/         DiagnosticRule interface, RulePolicy, the 15 public-core rules
  profile/       QueryProfile model, its collector, and the deep per-query rules
  report/        terminal/HTML renderers (scan) and the query text renderer
  anonymizer/    Snapshot -> pseudonymized Snapshot (Milestone 16)
  baseline/      local SQLite store, pairwise compare, multi-point history
  explain/       ExplanationProvider interface + local llama.cpp implementation
  cli/           click commands, wiring all of the above together
```
