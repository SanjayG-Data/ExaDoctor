"""Unified QueryProfile model (roadmap section 6.3, Milestone 8) -- public-only build.

Fields the roadmap reserves for internal-only detail (`in_rows`, `mem_peak`,
`process_id`, `node_id`, per-part `start_time`/`stop_time`) stay `None`
here: `EXA_DBA_PROFILE_LAST_DAY`/`EXA_DBA_PROFILE_RUNNING` (verified live in
Milestone 0) do not carry them. See docs/internal-interface-policy.md.

`PART_INFO` marker strings used below (`GLOBAL`, `EXPRESSION INDEX`,
`TEMPORARY`) are Exasol's own documented vocabulary for that column (from
the system catalog's column comment on `EXA_DBA_PROFILE_LAST_DAY.
PART_INFO`), not invented here -- but that comment also documents `NL
JOIN` and `REPLICATED`, which nothing here checks for; this is a deliberate
subset, not a claim of exhaustiveness. A live query with genuinely multiple profile parts
using these markers has not been observed on this test instance (profiling
is not broadly enabled there; only a single-part ROLLBACK row exists). Any
rule relying on these markers is therefore verified against the documented
vocabulary and synthetic fixtures only, not live multi-part data -- treat
as unproven until that live check happens (same caveat the roadmap itself
applies to process/node skew).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_GLOBAL_MARKER = "GLOBAL"
_EXPRESSION_INDEX_MARKER = "EXPRESSION INDEX"
_TEMPORARY_MARKER = "TEMPORARY"


@dataclass
class QueryProfilePart:
    part_id: int
    part_name: str
    part_info: str | None
    object_schema: str | None
    object_name: str | None
    object_rows: int | None
    in_rows: int | None
    out_rows: int | None
    duration: float | None
    cpu: float | None
    temp_db_ram_peak: float | None
    mem_peak: float | None
    local_read_size: float | None
    remote_read_size: float | None
    network: float | None
    process_id: int | None
    node_id: str | None
    start_time: datetime | None
    stop_time: datetime | None
    remarks: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "part_name": self.part_name,
            "part_info": self.part_info,
            "object_schema": self.object_schema,
            "object_name": self.object_name,
            "object_rows": self.object_rows,
            "in_rows": self.in_rows,
            "out_rows": self.out_rows,
            "duration": self.duration,
            "cpu": self.cpu,
            "temp_db_ram_peak": self.temp_db_ram_peak,
            "mem_peak": self.mem_peak,
            "local_read_size": self.local_read_size,
            "remote_read_size": self.remote_read_size,
            "network": self.network,
            "process_id": self.process_id,
            "node_id": self.node_id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "stop_time": self.stop_time.isoformat() if self.stop_time else None,
            "remarks": self.remarks,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryProfilePart:
        return cls(
            part_id=data["part_id"],
            part_name=data["part_name"],
            part_info=data["part_info"],
            object_schema=data["object_schema"],
            object_name=data["object_name"],
            object_rows=data["object_rows"],
            in_rows=data["in_rows"],
            out_rows=data["out_rows"],
            duration=data["duration"],
            cpu=data["cpu"],
            temp_db_ram_peak=data["temp_db_ram_peak"],
            mem_peak=data["mem_peak"],
            local_read_size=data["local_read_size"],
            remote_read_size=data["remote_read_size"],
            network=data["network"],
            process_id=data["process_id"],
            node_id=data["node_id"],
            start_time=datetime.fromisoformat(data["start_time"]) if data["start_time"] else None,
            stop_time=datetime.fromisoformat(data["stop_time"]) if data["stop_time"] else None,
            remarks=data["remarks"],
        )


@dataclass
class QueryProfile:
    session_id: int
    stmt_id: int
    source: str  # "EXA_DBA_PROFILE_LAST_DAY" | "EXA_DBA_PROFILE_RUNNING"
    parts: list[QueryProfilePart] = field(default_factory=list)

    def total_duration(self) -> float | None:
        durations = [p.duration for p in self.parts if p.duration is not None]
        return sum(durations) if durations else None

    def dominant_part(self) -> QueryProfilePart | None:
        timed = [p for p in self.parts if p.duration is not None]
        return max(timed, key=lambda p: p.duration) if timed else None

    def duration_share(self, part: QueryProfilePart) -> float | None:
        total = self.total_duration()
        if not total or part.duration is None:
            return None
        return part.duration / total

    def global_parts(self) -> list[QueryProfilePart]:
        return [p for p in self.parts if p.part_info and _GLOBAL_MARKER in p.part_info]

    def expression_index_parts(self) -> list[QueryProfilePart]:
        return [p for p in self.parts if p.part_info and _EXPRESSION_INDEX_MARKER in p.part_info]

    def temporary_parts(self) -> list[QueryProfilePart]:
        return [p for p in self.parts if p.part_info and _TEMPORARY_MARKER in p.part_info]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "stmt_id": self.stmt_id,
            "source": self.source,
            "parts": [p.to_dict() for p in self.parts],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryProfile:
        return cls(
            session_id=data["session_id"],
            stmt_id=data["stmt_id"],
            source=data["source"],
            parts=[QueryProfilePart.from_dict(p) for p in data["parts"]],
        )
