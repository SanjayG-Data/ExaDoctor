"""Unit tests for exadoctor.anonymizer (roadmap section 12.2, Milestone 16).

Uses the golden fixture Snapshot (tests/golden/sample_snapshot.json) so the
shape under test matches what a live-built Snapshot actually looks like,
rather than a hand-rolled minimal object graph.
"""

from __future__ import annotations

import json
from pathlib import Path

from exadoctor.anonymizer import AnonymizationResult, PseudonymMapper, anonymize_snapshot
from exadoctor.models.snapshot import Snapshot

FIXTURE_PATH = Path(__file__).parent.parent / "golden" / "sample_snapshot.json"


def _load_snapshot() -> Snapshot:
    return Snapshot.from_dict(json.loads(FIXTURE_PATH.read_text()))


# --- PseudonymMapper -----------------------------------------------------


def test_pseudonym_mapper_is_stable_for_same_value() -> None:
    mapper = PseudonymMapper()
    first = mapper.pseudonym_for("user", "ALICE")
    second = mapper.pseudonym_for("user", "ALICE")
    assert first == second == "USER_1"


def test_pseudonym_mapper_assigns_distinct_pseudonyms_for_distinct_values() -> None:
    mapper = PseudonymMapper()
    alice = mapper.pseudonym_for("user", "ALICE")
    bob = mapper.pseudonym_for("user", "BOB")
    assert alice != bob
    assert {alice, bob} == {"USER_1", "USER_2"}


def test_pseudonym_mapper_namespaces_categories_separately() -> None:
    mapper = PseudonymMapper()
    user_pseudonym = mapper.pseudonym_for("user", "MAIN")
    cluster_pseudonym = mapper.pseudonym_for("cluster", "MAIN")
    # Same real string, different category -> independent numbering, no collision.
    assert user_pseudonym == "USER_1"
    assert cluster_pseudonym == "CLUSTER_1"
    assert user_pseudonym != cluster_pseudonym


def test_pseudonym_mapper_mapping_is_grouped_by_category() -> None:
    mapper = PseudonymMapper()
    mapper.pseudonym_for("user", "ALICE")
    mapper.pseudonym_for("host", "db01.internal")
    mapping = mapper.mapping()
    assert mapping == {
        "user": {"ALICE": "USER_1"},
        "host": {"db01.internal": "HOST_1"},
    }


# --- anonymize_snapshot ---------------------------------------------------


def test_anonymize_snapshot_returns_anonymization_result() -> None:
    snapshot = _load_snapshot()
    result = anonymize_snapshot(snapshot)
    assert isinstance(result, AnonymizationResult)
    assert isinstance(result.snapshot, Snapshot)
    assert isinstance(result.mapping, dict)


def test_same_real_value_maps_to_same_pseudonym_everywhere_in_one_run() -> None:
    snapshot = _load_snapshot()
    # The fixture uses cluster_name="MAIN" in sessions, workload, monitoring,
    # storage is empty, and usage -- all should collapse to one pseudonym.
    result = anonymize_snapshot(snapshot)

    cluster_pseudonyms = set()
    cluster_pseudonyms.update(s.cluster_name for s in result.snapshot.sessions.rows if s.cluster_name)
    cluster_pseudonyms.update(s.cluster_name for s in result.snapshot.workload.rows if s.cluster_name)
    cluster_pseudonyms.update(s.cluster_name for s in result.snapshot.monitoring.rows if s.cluster_name)
    cluster_pseudonyms.update(s.cluster_name for s in result.snapshot.usage.rows if s.cluster_name)

    assert cluster_pseudonyms == {"CLUSTER_1"}
    assert result.mapping["cluster"] == {"MAIN": "CLUSTER_1"}


def test_different_real_values_get_different_pseudonyms() -> None:
    mapper_input = _load_snapshot()
    # Add a second, distinct user session so we can confirm the mapper
    # doesn't collapse distinct real values together.
    from dataclasses import replace

    extra_session = replace(mapper_input.sessions.rows[0], session_id=999, user_name="ANOTHER_USER")
    mapper_input.sessions.rows.append(extra_session)

    result = anonymize_snapshot(mapper_input)
    user_pseudonyms = {s.user_name for s in result.snapshot.sessions.rows}

    assert len(user_pseudonyms) == 2
    assert result.mapping["user"]["SYS"] != result.mapping["user"]["ANOTHER_USER"]


def test_anonymized_snapshot_json_contains_no_real_identity_values() -> None:
    # The fixture's own values ("SYS", "MAIN") are too generic for a clean
    # substring check: "SYS" is also a substring of the static system
    # schema quoting in Capability.source ('"SYS"."EXA_METADATA"'), which
    # is not customer identity and is never anonymized (see anonymizer.py
    # docstring). Swap in distinctive, realistic customer-like identity
    # values on the loaded fixture Snapshot so the substring check below
    # actually exercises the "no real identity leaks" guarantee, while
    # still using the golden fixture for the overall Snapshot shape.
    snapshot = _load_snapshot()
    snapshot.database.host = "acme-prod-db01.internal.example.com"
    for session in snapshot.sessions.rows:
        session.user_name = "JDOE_ACME_ADMIN"
        session.cluster_name = "ACME_PROD_CLUSTER_EAST"
    for statement in snapshot.workload.rows:
        statement.cluster_name = "ACME_PROD_CLUSTER_EAST"
    for sample in snapshot.monitoring.rows:
        sample.cluster_name = "ACME_PROD_CLUSTER_EAST"
    for sample in snapshot.usage.rows:
        sample.cluster_name = "ACME_PROD_CLUSTER_EAST"

    real_host = snapshot.database.host
    real_users = {s.user_name for s in snapshot.sessions.rows}
    real_clusters: set[str] = set()
    real_clusters.update(s.cluster_name for s in snapshot.sessions.rows if s.cluster_name)
    real_clusters.update(s.cluster_name for s in snapshot.workload.rows if s.cluster_name)
    real_clusters.update(s.cluster_name for s in snapshot.monitoring.rows if s.cluster_name)
    real_clusters.update(s.cluster_name for s in snapshot.storage.rows if s.cluster_name)
    real_clusters.update(s.cluster_name for s in snapshot.usage.rows if s.cluster_name)

    result = anonymize_snapshot(snapshot)
    payload = json.dumps(result.snapshot.to_dict())

    assert real_host not in payload
    for user in real_users:
        assert user not in payload
    for cluster in real_clusters:
        assert cluster not in payload

    # Sanity: the pseudonyms actually ARE present (i.e. we didn't just wipe fields).
    assert "HOST_1" in payload
    assert "USER_1" in payload
    assert "CLUSTER_1" in payload


def test_anonymize_snapshot_does_not_mutate_input() -> None:
    snapshot = _load_snapshot()
    original_host = snapshot.database.host
    original_user_name = snapshot.sessions.rows[0].user_name
    original_cluster_name = snapshot.sessions.rows[0].cluster_name

    anonymize_snapshot(snapshot)

    assert snapshot.database.host == original_host
    assert snapshot.sessions.rows[0].user_name == original_user_name
    assert snapshot.sessions.rows[0].cluster_name == original_cluster_name


def test_anonymize_snapshot_leaves_numeric_and_timestamp_fields_untouched() -> None:
    snapshot = _load_snapshot()
    result = anonymize_snapshot(snapshot)

    original_stmt = snapshot.workload.rows[0]
    anonymized_stmt = result.snapshot.workload.rows[0]

    assert anonymized_stmt.duration_seconds == original_stmt.duration_seconds
    assert anonymized_stmt.cpu_percent == original_stmt.cpu_percent
    assert anonymized_stmt.row_count == original_stmt.row_count
    assert anonymized_stmt.success == original_stmt.success
    assert anonymized_stmt.start_time == original_stmt.start_time
    assert anonymized_stmt.stop_time == original_stmt.stop_time
    assert anonymized_stmt.session_id == original_stmt.session_id
    assert anonymized_stmt.stmt_id == original_stmt.stmt_id

    original_session = snapshot.sessions.rows[0]
    anonymized_session = result.snapshot.sessions.rows[0]
    assert anonymized_session.duration_seconds == original_session.duration_seconds
    assert anonymized_session.temp_db_ram_mib == original_session.temp_db_ram_mib
    assert anonymized_session.persistent_db_ram_mib == original_session.persistent_db_ram_mib
    assert anonymized_session.login_time == original_session.login_time
    assert anonymized_session.session_id == original_session.session_id
    # consumer_group is deliberately left alone (see anonymizer.py docstring).
    assert anonymized_session.consumer_group == original_session.consumer_group


def test_anonymize_snapshot_preserves_database_version_and_port() -> None:
    snapshot = _load_snapshot()
    result = anonymize_snapshot(snapshot)
    assert result.snapshot.database.port == snapshot.database.port
    assert result.snapshot.database.version == snapshot.database.version
    assert result.snapshot.database.host != snapshot.database.host
