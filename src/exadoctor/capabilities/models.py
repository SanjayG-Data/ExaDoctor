"""Normalized capability model (roadmap section 6.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Capability:
    id: str
    available: bool
    reason: str | None
    source: str
    stability: str  # "PUBLIC" | "INTERNAL" | "EXPERIMENTAL"
    database_version: str | None
    privilege_required: str | None
    detected_columns: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)
    data_available: bool | None = None
    detected_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "available": self.available,
            "reason": self.reason,
            "source": self.source,
            "stability": self.stability,
            "database_version": self.database_version,
            "privilege_required": self.privilege_required,
            "detected_columns": list(self.detected_columns),
            "missing_columns": list(self.missing_columns),
            "data_available": self.data_available,
            "detected_at": self.detected_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Capability:
        return cls(
            id=data["id"],
            available=data["available"],
            reason=data["reason"],
            source=data["source"],
            stability=data["stability"],
            database_version=data["database_version"],
            privilege_required=data["privilege_required"],
            detected_columns=list(data["detected_columns"]),
            missing_columns=list(data["missing_columns"]),
            data_available=data["data_available"],
            detected_at=datetime.fromisoformat(data["detected_at"]),
        )
