# Internal `$EXA_*` interface policy

**Decision (2026-08-22): ExaDoctor does not use `$EXA_*` internal diagnostic
tables.** This is a deliberate scope decision, not a deferral pending future
access.

## Rationale

- `$EXA_*` tables (`$EXA_PROFILE_LAST_DAY`, `$EXA_PROFILE_RUNNING`,
  `$EXA_STATS_PROFILE_PARTS`, `$EXA_PROFILE_SQL_RUNNING`) are undocumented
  support/engineering interfaces with no compatibility guarantee across Exasol
  versions.
- Relying on them would require version-specific adapters (v8 / 2025.x / 2026.x
  boundaries), a mandatory internal-schema contract test suite, and ongoing
  maintenance every time Exasol ships a new internal profiling schema.
- ExaDoctor is distributed externally; dependence on undocumented
  interfaces would create support/licensing ambiguity that a
  public-sources-only tool avoids entirely.
- Concretely verified in [`capability-matrix.md`](capability-matrix.md): the public
  `EXA_DBA_PROFILE_LAST_DAY` / `EXA_DBA_PROFILE_RUNNING` tables do **not**
  expose `IN_ROWS`, so row-expansion and NODE SYNC analysis have no public
  fallback. That capability gap is accepted.

## What this means for the diagnostic engine

The following derived diagnostics are permanently `NOT_EVALUATED` rather than
temporarily unavailable:

- IN_ROWS / OUT_ROWS row-expansion analysis (`PERF-ROW-EXPANSION-001`)
- NODE SYNC wait analysis (`PERF-NODE-SYNC-001`)
- Per-process imbalance / skew (`PERF-SKEW-001`)
- Any rule whose only source in the original roadmap was a `$EXA_*` table with
  no public equivalent (see the roadmap's §4.1 fallback table)

Everything else in the roadmap's rule catalogue (§8.1 public-core rules, plus
the deep rules whose evidence is satisfiable from `EXA_DBA_PROFILE_LAST_DAY` /
`EXA_SQL_LAST_DAY` — e.g. dominant-part bottleneck, TEMP materialization,
GLOBAL/network correlation) remains in scope.

## Architectural consequence

The `ProfileRepository`-style interface boundary from the roadmap (§7.1) is
still followed: collectors and rules depend on normalized models, never on raw
table names. If a future decision reverses this policy, an internal adapter
can be added underneath that interface without touching rule code — but no
such adapter exists today, and none should be added without a new explicit
decision recorded here.
