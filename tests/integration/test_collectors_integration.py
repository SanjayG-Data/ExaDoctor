"""Integration layer (roadmap section 11.1): exercises real Exasol behavior.

Skipped unless EXADOCTOR_HOST/USER/PASSWORD are set in the environment --
this suite is meant to run against a real instance (e.g. a local Exasol
Docker-DB), not in ordinary unit test runs. Verified manually against a live
Exasol 2026.1.0 instance during Milestone 3; kept here so the same check is
repeatable rather than a one-off script.
"""

from __future__ import annotations

import os

import pytest

from exadoctor.collectors import collect_all
from exadoctor.connection.config import ConnectionConfig
from exadoctor.connection.gateway import ReadOnlyGateway

pytestmark = pytest.mark.skipif(
    not os.environ.get("EXADOCTOR_HOST"),
    reason="Integration tests require a live Exasol instance (EXADOCTOR_HOST/USER/PASSWORD).",
)


def test_collect_all_against_live_instance() -> None:
    config = ConnectionConfig.from_env()
    with ReadOnlyGateway(config) as gateway:
        results = collect_all(gateway)

    assert set(results.keys()) == {
        "metadata",
        "parameters",
        "sessions",
        "workload",
        "monitoring",
        "storage",
        "usage",
    }
    for name, result in results.items():
        assert result.available, f"{name} unexpectedly unavailable: {result.reason}"

    metadata_rows = {row.param_name: row.param_value for row in results["metadata"].rows}
    assert "databaseProductVersion" in metadata_rows
