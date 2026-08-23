"""Local SQLite-backed store for named baseline Snapshots (roadmap Milestones
17-18: "Store local snapshots in SQLite or a simple versioned store").

Design decisions
-----------------
- **History, not overwrite.** Saving the same name twice inserts a new row
  rather than replacing the old one; `load_baseline` always returns the most
  recent row for that name. The roadmap explicitly calls out "trend metrics"
  as a goal, and a pure overwrite would destroy the very history a future
  `exadoctor baseline history <name>` (or a "trend over the last N baselines"
  view) would need. The storage cost of keeping full Snapshot JSON blobs
  around is accepted as a reasonable tradeoff for a local, user-owned SQLite
  file the user explicitly chose to create via `baseline create`.
- **Location follows the `ConnectionConfig.from_env()` pattern**: a single
  module-level env var name (`EXADOCTOR_BASELINE_DB`), a sensible default
  under the user's home directory, and a plain resolver function rather than
  a dataclass -- there is no cluster of related settings here (unlike
  connection config's host/port/user/password/...), so a dataclass would be
  ceremony without benefit.
- **No credentials, ever.** A `Snapshot` is structurally incapable of holding
  credentials (see `exadoctor.models.snapshot`); this module only ever
  serializes `Snapshot.to_dict()` output, so it inherits that guarantee
  rather than needing to re-implement it.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from exadoctor.errors import BaselineNotFoundError, OutputWriteError
from exadoctor.models.snapshot import Snapshot

BASELINE_DB_VAR = "EXADOCTOR_BASELINE_DB"

DEFAULT_BASELINE_DB_PATH = Path.home() / ".exadoctor" / "baselines.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL
)
"""

_CREATE_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_baselines_name ON baselines (name)"


@dataclass(frozen=True)
class BaselineRecord:
    """Lightweight (name, created_at) summary -- for `baseline list`, not the
    full Snapshot payload."""

    name: str
    created_at: datetime


def resolve_baseline_db_path(db_path: str | None = None) -> Path:
    """Resolve the SQLite file to use, following the same override order as
    `ConnectionConfig.from_env`: explicit argument > environment variable >
    built-in default."""
    if db_path:
        return Path(db_path)
    env_value = os.environ.get(BASELINE_DB_VAR)
    if env_value:
        return Path(env_value)
    return DEFAULT_BASELINE_DB_PATH


@contextmanager
def _connect(db_path: str | None) -> Iterator[sqlite3.Connection]:
    path = resolve_baseline_db_path(db_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
    except (OSError, sqlite3.Error) as exc:
        # Found by independent QA: an unwritable/overlong EXADOCTOR_BASELINE_DB
        # path previously raised a raw OSError straight through every
        # baseline command -- a full traceback for an ordinary path typo.
        raise OutputWriteError(
            f"Could not open the baseline store at {path}: {exc.__class__.__name__}: {exc}"
        ) from exc
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_INDEX_SQL)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_baseline(name: str, snapshot: Snapshot, db_path: str | None = None) -> None:
    """Persist `snapshot` as a new version under `name`.

    Uses the exact `Snapshot.to_dict()` / `Snapshot.from_dict()` JSON
    contract used everywhere else in ExaDoctor (e.g. `scan --format json`,
    the golden fixture) -- no separate serialization format is invented.
    """
    created_at = datetime.now(timezone.utc).isoformat()
    snapshot_json = json.dumps(snapshot.to_dict())
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO baselines (name, created_at, snapshot_json) VALUES (?, ?, ?)",
            (name, created_at, snapshot_json),
        )


def load_baseline(name: str, db_path: str | None = None) -> Snapshot:
    """Load the most recently saved Snapshot for `name`.

    Raises `BaselineNotFoundError` (a typed `ExaDoctorError`, not a bare
    `KeyError`/`LookupError`) if no baseline with that name has ever been
    saved to this store.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT snapshot_json FROM baselines WHERE name = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (name,),
        ).fetchone()

    if row is None:
        resolved_path = resolve_baseline_db_path(db_path)
        raise BaselineNotFoundError(
            f"No baseline named {name!r} found in {resolved_path}. "
            f"Run `exadoctor baseline create {name}` first."
        )

    return Snapshot.from_dict(json.loads(row[0]))


def load_baseline_history(name: str, db_path: str | None = None) -> list[Snapshot]:
    """All saved versions for `name`, oldest first.

    Unlike `load_baseline`, an unknown name returns an empty list rather
    than raising `BaselineNotFoundError` -- "no history yet" is a normal,
    expected state for `exadoctor baseline history`, not an error the way
    "the baseline to compare against doesn't exist" is for `compare`.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT snapshot_json FROM baselines WHERE name = ? ORDER BY created_at ASC, id ASC",
            (name,),
        ).fetchall()
    return [Snapshot.from_dict(json.loads(snapshot_json)) for (snapshot_json,) in rows]


def list_baselines(db_path: str | None = None) -> list[BaselineRecord]:
    """List every saved baseline version, most recent first.

    Because saves are versioned (see module docstring), the same `name` can
    appear more than once here -- each row is one `save_baseline` call. A
    future `exadoctor baseline list` can dedupe to "latest per name" or show
    full history as it prefers; this function does not decide that for it.
    """
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT name, created_at FROM baselines ORDER BY created_at DESC, id DESC").fetchall()
    return [BaselineRecord(name=name, created_at=datetime.fromisoformat(created_at)) for name, created_at in rows]
