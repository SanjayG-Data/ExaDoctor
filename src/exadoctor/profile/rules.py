"""Deep per-query profile rules (roadmap section 8.2), public-only subset.

Only rules whose evidence is satisfiable from the public profile
(EXA_DBA_PROFILE_LAST_DAY/RUNNING: PART_NAME, PART_INFO, DURATION, NET,
TEMP_DB_RAM_PEAK) are implemented. IN_ROWS-based row-expansion, NODE SYNC,
and per-process skew rules are permanently out of scope -- see
docs/internal-interface-policy.md.

Every PART_INFO-marker rule here (GLOBAL, EXPRESSION INDEX, TEMPORARY) uses
Exasol's own documented vocabulary for that column, but has not yet been
observed against genuinely multi-part live data (profiling is not broadly
enabled on the available test instance -- see profile/models.py). Treat as
fixture-tested, not live-proven, matching the roadmap's own standard for
other unproven deep diagnostics (e.g. process/node skew).
"""

from __future__ import annotations

from collections.abc import Callable

from exadoctor.models.finding import Evidence, Finding, FindingStatus
from exadoctor.profile.models import QueryProfile
from exadoctor.rules.policy import RulePolicy

_REQUIREMENTS = ["EXA_DBA_PROFILE_LAST_DAY or EXA_DBA_PROFILE_RUNNING"]


def evaluate_bottleneck(profile: QueryProfile, policy: RulePolicy) -> list[Finding]:
    if not profile.parts:
        return [
            Finding(
                id="PERF-BOTTLENECK-001",
                title="No profile parts",
                category="query",
                status=FindingStatus.NOT_EVALUATED,
                summary="No execution parts available for this statement.",
                confidence="LOW",
                requirements=_REQUIREMENTS,
            )
        ]

    dominant = profile.dominant_part()
    total = profile.total_duration()
    # `total == 0.0` is real data (a sub-millisecond statement, DURATION is
    # DECIMAL(12,3)), not missing evidence -- only `None` means no part
    # carried a DURATION at all. Conflating the two previously misreported
    # a genuinely fast statement as NOT_EVALUATED (caught via live testing).
    if dominant is None or total is None:
        return [
            Finding(
                id="PERF-BOTTLENECK-001",
                title="No timed profile parts",
                category="query",
                status=FindingStatus.NOT_EVALUATED,
                summary="Profile parts exist but none carry a DURATION value.",
                confidence="LOW",
                requirements=_REQUIREMENTS,
            )
        ]
    if total == 0:
        return [
            Finding(
                id="PERF-BOTTLENECK-001",
                title="Negligible statement duration",
                category="query",
                status=FindingStatus.PASS,
                summary=(
                    f"Total profiled duration across {len(profile.parts)} part(s) rounds to 0.000s; "
                    "no meaningful dominant-part analysis applies."
                ),
                confidence="MEDIUM",
                requirements=_REQUIREMENTS,
            )
        ]

    share = profile.duration_share(dominant) or 0.0
    status = FindingStatus.WARNING if share >= policy.dominant_part_share_threshold else FindingStatus.INFO
    return [
        Finding(
            id="PERF-BOTTLENECK-001",
            title="Dominant execution part",
            category="query",
            status=status,
            summary=(
                f"Part #{dominant.part_id} ({dominant.part_name}) accounts for {share * 100:.0f}% of "
                f"statement duration ({dominant.duration:.3f}s of {total:.3f}s total)."
            ),
            evidence=[
                Evidence(
                    source=profile.source,
                    stability="PUBLIC",
                    metric="DURATION",
                    value=dominant.duration,
                    unit="seconds",
                    timestamp=None,
                    context=f"part={dominant.part_name} share={share * 100:.0f}%",
                    session_id=profile.session_id,
                    stmt_id=profile.stmt_id,
                    part_id=dominant.part_id,
                )
            ],
            recommendation=(
                "Focus tuning effort on this part -- it dominates the statement's runtime."
                if status == FindingStatus.WARNING
                else None
            ),
            confidence="MEDIUM",
            requirements=_REQUIREMENTS,
            documentation=["ExaDoctor policy: dominant-part share threshold"],
        )
    ]


def evaluate_global_operation(profile: QueryProfile, policy: RulePolicy) -> list[Finding]:
    global_parts = profile.global_parts()
    if not global_parts:
        return [
            Finding(
                id="PERF-GLOBAL-001",
                title="No GLOBAL operations",
                category="query",
                status=FindingStatus.PASS,
                summary="No execution part is marked GLOBAL.",
                confidence="MEDIUM",
                requirements=_REQUIREMENTS,
                documentation=["Exasol documentation: PART_INFO column vocabulary"],
            )
        ]

    findings: list[Finding] = []
    for part in global_parts:
        net_note = f", network {part.network:.1f} MiB/s" if part.network else ""
        findings.append(
            Finding(
                id="PERF-GLOBAL-001",
                title="Global operation with network cost",
                category="query",
                status=FindingStatus.INFO,
                summary=f"Part #{part.part_id} ({part.part_name}) is a GLOBAL operation{net_note}.",
                evidence=[
                    Evidence(
                        source=profile.source,
                        stability="PUBLIC",
                        metric="PART_INFO",
                        value=part.part_info,
                        unit=None,
                        timestamp=None,
                        context=f"part={part.part_name}",
                        session_id=profile.session_id,
                        stmt_id=profile.stmt_id,
                        part_id=part.part_id,
                    )
                ],
                recommendation=(
                    "GLOBAL operations redistribute data across nodes; correlate with NET/duration "
                    "if this statement is unexpectedly slow."
                ),
                confidence="MEDIUM",
                requirements=_REQUIREMENTS,
                documentation=["Exasol documentation: PART_INFO column vocabulary"],
            )
        )
    return findings


def evaluate_expression_index(profile: QueryProfile, policy: RulePolicy) -> list[Finding]:
    parts = profile.expression_index_parts()
    if not parts:
        return [
            Finding(
                id="PERF-EXPR-INDEX-001",
                title="No expression index construction",
                category="query",
                status=FindingStatus.PASS,
                summary="No execution part indicates expression index construction.",
                confidence="MEDIUM",
                requirements=_REQUIREMENTS,
                documentation=["Exasol documentation: PART_INFO column vocabulary"],
            )
        ]

    findings: list[Finding] = []
    for part in parts:
        share = profile.duration_share(part)
        share_note = f" ({share * 100:.0f}% of statement duration)" if share is not None else ""
        findings.append(
            Finding(
                id="PERF-EXPR-INDEX-001",
                title="Expression index construction",
                category="query",
                status=FindingStatus.WARNING,
                summary=(
                    f"Part #{part.part_id} ({part.part_name}, object {part.object_schema}.{part.object_name}) "
                    f"builds an expression index{share_note}."
                ),
                evidence=[
                    Evidence(
                        source=profile.source,
                        stability="PUBLIC",
                        metric="DURATION",
                        value=part.duration,
                        unit="seconds",
                        timestamp=None,
                        context=f"object={part.object_schema}.{part.object_name}",
                        session_id=profile.session_id,
                        stmt_id=profile.stmt_id,
                        part_id=part.part_id,
                    )
                ],
                recommendation=(
                    "Expression index construction is expensive; consider whether the index can be "
                    "created ahead of time rather than inline in this statement."
                ),
                confidence="MEDIUM",
                requirements=_REQUIREMENTS,
                documentation=["Exasol documentation: PART_INFO column vocabulary"],
            )
        )
    return findings


def evaluate_temp_materialization(profile: QueryProfile, policy: RulePolicy) -> list[Finding]:
    parts = [p for p in profile.parts if p.temp_db_ram_peak is not None and p.temp_db_ram_peak > 0]
    if not parts:
        return [
            Finding(
                id="PERF-TEMP-MATERIALIZE-001",
                title="No TEMP materialization",
                category="query",
                status=FindingStatus.PASS,
                summary="No execution part reported TEMP memory usage.",
                confidence="MEDIUM",
                requirements=_REQUIREMENTS,
            )
        ]

    worst = max(parts, key=lambda p: p.temp_db_ram_peak)
    # `is`, not `in`: QueryProfilePart is a mutable dataclass with value
    # equality, so `in` would treat two structurally-identical parts (e.g.
    # repeated identical scan sub-parts) as interchangeable -- wrong
    # semantics for "is THIS specific part marked TEMPORARY".
    is_marked_temporary = any(worst is p for p in profile.temporary_parts())
    status = (
        FindingStatus.WARNING
        if (is_marked_temporary or worst.temp_db_ram_peak >= policy.temp_materialize_mib_threshold)
        else FindingStatus.INFO
    )
    out_rows_note = worst.out_rows if worst.out_rows is not None else "unknown"
    return [
        Finding(
            id="PERF-TEMP-MATERIALIZE-001",
            title="Temporary materialization",
            category="query",
            status=status,
            summary=(
                f"Part #{worst.part_id} ({worst.part_name}) used {worst.temp_db_ram_peak:.1f} MiB of TEMP memory"
                + (" (marked TEMPORARY)" if is_marked_temporary else "")
                + f", with {out_rows_note} output rows."
            ),
            evidence=[
                Evidence(
                    source=profile.source,
                    stability="PUBLIC",
                    metric="TEMP_DB_RAM_PEAK",
                    value=worst.temp_db_ram_peak,
                    unit="MiB",
                    timestamp=None,
                    context=f"part={worst.part_name} out_rows={worst.out_rows}",
                    session_id=profile.session_id,
                    stmt_id=profile.stmt_id,
                    part_id=worst.part_id,
                )
            ],
            recommendation=(
                "Review whether this materialization is necessary; large TEMP usage in one part often "
                "correlates with sorts/joins/aggregations that could be restructured."
            ),
            confidence="MEDIUM",
            requirements=_REQUIREMENTS,
            documentation=(
                ["Exasol documentation: PART_INFO column vocabulary"]
                if is_marked_temporary
                else ["ExaDoctor policy: TEMP materialization threshold"]
            ),
        )
    ]


PERF_RULES: list[Callable[[QueryProfile, RulePolicy], list[Finding]]] = [
    evaluate_bottleneck,
    evaluate_global_operation,
    evaluate_expression_index,
    evaluate_temp_materialization,
]


def evaluate_query_profile(profile: QueryProfile, policy: RulePolicy) -> list[Finding]:
    findings: list[Finding] = []
    for rule_fn in PERF_RULES:
        try:
            findings.extend(rule_fn(profile, policy))
        except Exception as exc:  # noqa: BLE001 - one rule must never abort the others
            findings.append(
                Finding(
                    id="PERF-UNKNOWN",
                    title="Rule error",
                    category="query",
                    status=FindingStatus.NOT_EVALUATED,
                    summary=f"A profile rule raised an unexpected error: {exc.__class__.__name__}: {exc}",
                    confidence="LOW",
                )
            )
    return findings
