"""Integration layer: build_snapshot against a real Exasol instance.

Skipped unless EXADOCTOR_HOST is set -- see test_collectors_integration.py.
"""

from __future__ import annotations

import json
import os

import pytest

from exadoctor.connection.config import ConnectionConfig
from exadoctor.connection.gateway import ReadOnlyGateway
from exadoctor.models.snapshot import Snapshot, build_snapshot

pytestmark = pytest.mark.skipif(
    not os.environ.get("EXADOCTOR_HOST"),
    reason="Integration tests require a live Exasol instance (EXADOCTOR_HOST/USER/PASSWORD).",
)


def test_build_snapshot_against_live_instance_round_trips() -> None:
    config = ConnectionConfig.from_env()
    with ReadOnlyGateway(config) as gateway:
        snapshot = build_snapshot(gateway, host=config.host, port=config.port)

    assert snapshot.database.version is not None
    assert snapshot.database_time is not None
    assert snapshot.database_time.tzinfo is None  # naive Exasol server civil time
    assert len(snapshot.capabilities) == 12
    assert all(c.available for c in snapshot.capabilities)
    assert snapshot.metadata.available is True

    payload = json.dumps(snapshot.to_dict())
    assert config.password not in payload

    restored = Snapshot.from_dict(json.loads(payload))
    assert restored == snapshot
