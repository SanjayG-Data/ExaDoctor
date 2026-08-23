"""Produce a support-shareable Snapshot with identity redacted.

Roadmap section 12.2 and Milestone 16 require that ExaDoctor be able to
produce a version of a Snapshot suitable for sharing with a third party
(e.g. Exasol support) with identifying information replaced by stable
pseudonyms, and that this anonymization be "stable within a report": the
same real value must map to the same pseudonym everywhere it appears in
one Snapshot.

`anonymize_snapshot` returns a NEW Snapshot -- the input is never mutated,
because anonymization runs against a `copy.deepcopy` of it -- with every
occurrence of a real user name, host, or cluster name replaced by a
pseudonym minted by `exadoctor.anonymizer.pseudonyms.PseudonymMapper`.

Fields anonymized (identity-bearing, confirmed by reading
`exadoctor.collectors.models` and `exadoctor.models.snapshot` field by
field -- nothing here is guessed):

    * DatabaseInfo.host               -> category "host"
    * SessionInfo.user_name           -> category "user"
    * SessionInfo.cluster_name        -> category "cluster"
    * SqlStatement.cluster_name       -> category "cluster"
    * MonitorSample.cluster_name      -> category "cluster"
    * DbSizeDailySample.cluster_name  -> category "cluster"
    * UsageSample.cluster_name        -> category "cluster"

Fields deliberately left alone, and why:

    * Every numeric metric, duration, timestamp, status, boolean, error
      code, and id (SESSION_ID, STMT_ID, ROW_COUNT, cpu_percent, *_mib,
      load, net_mib_per_sec, users, queries, etc.) -- these are not
      identity, and rewriting them would make the shared report useless
      for actual diagnosis.
    * SessionInfo.consumer_group -- CONSUMER_GROUP names *can* be
      customer-chosen (e.g. named after a team or department) and so
      could carry some organizational identity, but the roadmap's stated
      identity list (user names, hostnames, schema/table names, cluster
      names) does not mention consumer groups, and the sample data in this
      codebase treats it as workload metadata (e.g. "SYS_CONSUMER_GROUP")
      rather than as an identity value. Left untouched per "when unsure,
      leave it alone and note it" -- flag as a candidate category if
      real-world support sharing raises a concern here.
    * SqlStatement.error_text and Evidence.context -- free text that CAN
      embed identity fragments (e.g. "table CUSTOMERSCHEMA.ORDERS not
      found", "insufficient privileges for user JDOE"), but there is no
      reliable way to find and redact those fragments by scanning free
      text: a naive substring-replace against the known pseudonym mapping
      is exactly the "unreliable string-replacement scanning" this task
      warns against, since it can just as easily miss a real value
      (different casing/quoting/escaping in the error message than in the
      structured field) or corrupt unrelated text (a real value that
      happens to be a common word or short identifier).
      **Known limitation**: this version does not scrub free-text fields.
      A "support-shareable" Snapshot's `error_text`/`context` values may
      still contain identity fragments and should be treated as sensitive
      -- and reviewed by a human before sharing -- until a proper
      parser-based approach (e.g. actually parsing the SQL error grammar)
      is built.
    * MetadataProperty (param_name/param_value) and Parameter
      (parameter_name/session_value/system_value) rows -- these carry
      Exasol system metadata/config names and values (e.g.
      "databaseProductVersion", "NLS_DATE_FORMAT"), not per-customer
      identity, in every case seen in the collectors and the golden
      fixture. Left alone; revisit if a real deployment's parameter values
      are ever found to embed a hostname or filesystem path.
    * Capability fields -- a Capability describes a *check* (id, source
      table, stability, required privilege), not the customer's data; per
      the task's own note and confirmed by reading
      `exadoctor.capabilities.models`, it carries no identity.
    * Finding.title/summary/recommendation/category/id and
      Evidence.source/metric/unit -- rule-authored, static text that is
      identical across every customer's report; not identity.

Known gap in the underlying data model (not addressed here -- out of
scope per this task's constraints, which forbid editing
`exadoctor.collectors`/`exadoctor.models`): the roadmap's identity list
also names schema and table names, but neither `SqlStatement` nor any
other row model here currently carries a schema/table field -- no
collector emits one today. `PseudonymMapper` already exposes "schema" and
"table" as first-class categories (see pseudonyms.py) precisely so that
whichever collector eventually adds such a field only needs one
`mapper.pseudonym_for("schema", ...)` / `("table", ...)` call added here,
with no redesign of the anonymizer itself.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from exadoctor.anonymizer.pseudonyms import (
    CATEGORY_CLUSTER,
    CATEGORY_HOST,
    CATEGORY_USER,
    PseudonymMapper,
)
from exadoctor.models.snapshot import Snapshot


@dataclass
class AnonymizationResult:
    """Result of `anonymize_snapshot`.

    Bundles the anonymized Snapshot together with the real-value ->
    pseudonym mapping used to build it, since the roadmap's "stable within
    a report" requirement is naturally verified/reused via that mapping
    (e.g. a caller may want to log how many distinct users/clusters were
    redacted) without ExaDoctor itself ever writing the mapping anywhere.

    `mapping` is purely in-memory and caller-controlled: this module never
    persists it. If a caller chooses to write it to disk for their own
    de-anonymization needs, they take on the responsibility that doing so
    -- especially sharing that file alongside the anonymized Snapshot --
    defeats the anonymization.
    """

    snapshot: Snapshot
    mapping: dict[str, dict[str, str]]


def anonymize_snapshot(snapshot: Snapshot) -> AnonymizationResult:
    """Return a support-shareable copy of `snapshot` with identity redacted.

    Does not mutate `snapshot` -- all anonymization happens on an
    independent `copy.deepcopy`. See the module docstring for exactly
    which fields are replaced by a stable pseudonym and which are
    deliberately left untouched.
    """
    mapper = PseudonymMapper()
    clone = copy.deepcopy(snapshot)

    clone.database.host = mapper.pseudonym_for(CATEGORY_HOST, clone.database.host)

    for session in clone.sessions.rows:
        session.user_name = mapper.pseudonym_for(CATEGORY_USER, session.user_name)
        if session.cluster_name is not None:
            session.cluster_name = mapper.pseudonym_for(CATEGORY_CLUSTER, session.cluster_name)

    for statement in clone.workload.rows:
        if statement.cluster_name is not None:
            statement.cluster_name = mapper.pseudonym_for(CATEGORY_CLUSTER, statement.cluster_name)

    for monitor_sample in clone.monitoring.rows:
        if monitor_sample.cluster_name is not None:
            monitor_sample.cluster_name = mapper.pseudonym_for(CATEGORY_CLUSTER, monitor_sample.cluster_name)

    for storage_sample in clone.storage.rows:
        if storage_sample.cluster_name is not None:
            storage_sample.cluster_name = mapper.pseudonym_for(CATEGORY_CLUSTER, storage_sample.cluster_name)

    for usage_sample in clone.usage.rows:
        if usage_sample.cluster_name is not None:
            usage_sample.cluster_name = mapper.pseudonym_for(CATEGORY_CLUSTER, usage_sample.cluster_name)

    return AnonymizationResult(snapshot=clone, mapping=mapper.mapping())
