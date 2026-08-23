"""Guards the on-disk Snapshot contract: a silent field rename/removal here
should fail this test rather than surface as an obscure downstream bug
when someone loads an old snapshot.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from exadoctor.models.snapshot import SCHEMA_VERSION, Snapshot

FIXTURE_PATH = Path(__file__).parent.parent / "golden" / "sample_snapshot.json"


def test_golden_fixture_loads_and_matches_current_schema_version() -> None:
    data = json.loads(FIXTURE_PATH.read_text())
    snapshot = Snapshot.from_dict(data)

    assert snapshot.schema_version == SCHEMA_VERSION
    assert snapshot.database.host == "localhost"
    assert snapshot.metadata.rows[0].param_name == "databaseProductVersion"
    assert snapshot.workload.rows[0].session_id == 1874035687682015232


def test_golden_fixture_round_trips_again() -> None:
    data = json.loads(FIXTURE_PATH.read_text())
    snapshot = Snapshot.from_dict(data)
    assert Snapshot.from_dict(json.loads(json.dumps(snapshot.to_dict()))) == snapshot
