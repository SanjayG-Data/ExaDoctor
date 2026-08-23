from __future__ import annotations

import json
from pathlib import Path

import pytest

from exadoctor.baseline.store import list_baselines, load_baseline, load_baseline_history, save_baseline
from exadoctor.errors import BaselineNotFoundError, OutputWriteError
from exadoctor.models.snapshot import Snapshot

FIXTURE_PATH = Path(__file__).parent.parent / "golden" / "sample_snapshot.json"


@pytest.fixture
def sample_snapshot() -> Snapshot:
    data = json.loads(FIXTURE_PATH.read_text())
    return Snapshot.from_dict(data)


def test_save_and_load_round_trip(tmp_path: Path, sample_snapshot: Snapshot) -> None:
    db_path = str(tmp_path / "baselines.db")

    save_baseline("production", sample_snapshot, db_path=db_path)
    loaded = load_baseline("production", db_path=db_path)

    assert loaded == sample_snapshot


def test_load_nonexistent_name_raises_typed_error(tmp_path: Path) -> None:
    db_path = str(tmp_path / "baselines.db")

    with pytest.raises(BaselineNotFoundError):
        load_baseline("does-not-exist", db_path=db_path)


def test_saving_same_name_twice_keeps_history(tmp_path: Path, sample_snapshot: Snapshot) -> None:
    db_path = str(tmp_path / "baselines.db")

    save_baseline("production", sample_snapshot, db_path=db_path)
    save_baseline("production", sample_snapshot, db_path=db_path)

    records = list_baselines(db_path=db_path)
    assert len([r for r in records if r.name == "production"]) == 2


def test_load_returns_most_recently_saved_version(tmp_path: Path, sample_snapshot: Snapshot) -> None:
    db_path = str(tmp_path / "baselines.db")

    older = Snapshot.from_dict(json.loads(FIXTURE_PATH.read_text()))
    older.workload.rows[0].command_name = "OLDER"
    save_baseline("production", older, db_path=db_path)

    newer = Snapshot.from_dict(json.loads(FIXTURE_PATH.read_text()))
    newer.workload.rows[0].command_name = "NEWER"
    save_baseline("production", newer, db_path=db_path)

    loaded = load_baseline("production", db_path=db_path)
    assert loaded.workload.rows[0].command_name == "NEWER"


def test_list_baselines_reflects_multiple_names(tmp_path: Path, sample_snapshot: Snapshot) -> None:
    db_path = str(tmp_path / "baselines.db")

    save_baseline("production", sample_snapshot, db_path=db_path)
    save_baseline("staging", sample_snapshot, db_path=db_path)

    names = {r.name for r in list_baselines(db_path=db_path)}
    assert names == {"production", "staging"}


def test_list_baselines_empty_store(tmp_path: Path) -> None:
    db_path = str(tmp_path / "baselines.db")
    assert list_baselines(db_path=db_path) == []


def test_default_db_path_is_not_touched_by_explicit_path(tmp_path: Path, sample_snapshot: Snapshot) -> None:
    # Regression guard: an explicit db_path must never fall through to the
    # real default location under the user's home directory.
    db_path = tmp_path / "baselines.db"
    save_baseline("production", sample_snapshot, db_path=str(db_path))
    assert db_path.exists()


def test_load_baseline_history_returns_empty_list_for_unknown_name(tmp_path: Path) -> None:
    # Unlike load_baseline, an unknown name is not an error here -- "no
    # history yet" is a normal state for `exadoctor baseline history`.
    db_path = str(tmp_path / "baselines.db")
    assert load_baseline_history("never-created", db_path=db_path) == []


def test_load_baseline_history_returns_all_versions_oldest_first(tmp_path: Path) -> None:
    db_path = str(tmp_path / "baselines.db")

    first = Snapshot.from_dict(json.loads(FIXTURE_PATH.read_text()))
    first.workload.rows[0].command_name = "FIRST"
    save_baseline("production", first, db_path=db_path)

    second = Snapshot.from_dict(json.loads(FIXTURE_PATH.read_text()))
    second.workload.rows[0].command_name = "SECOND"
    save_baseline("production", second, db_path=db_path)

    history = load_baseline_history("production", db_path=db_path)
    assert [s.workload.rows[0].command_name for s in history] == ["FIRST", "SECOND"]


def test_load_baseline_history_only_returns_matching_name(tmp_path: Path, sample_snapshot: Snapshot) -> None:
    db_path = str(tmp_path / "baselines.db")
    save_baseline("production", sample_snapshot, db_path=db_path)
    save_baseline("staging", sample_snapshot, db_path=db_path)

    assert len(load_baseline_history("production", db_path=db_path)) == 1


def test_unreachable_db_path_raises_typed_error_not_a_raw_oserror(tmp_path: Path, sample_snapshot: Snapshot) -> None:
    # Found by independent QA: an EXADOCTOR_BASELINE_DB path that can't be
    # created (e.g. a regular file sitting where a directory needs to be)
    # previously raised a raw OSError straight through every baseline
    # command -- a full Python traceback for an ordinary path mistake.
    blocking_file = tmp_path / "not_a_directory.txt"
    blocking_file.write_text("blocking")
    bad_db_path = str(blocking_file / "nested" / "baselines.db")

    with pytest.raises(OutputWriteError, match="Could not open the baseline store"):
        save_baseline("production", sample_snapshot, db_path=bad_db_path)
