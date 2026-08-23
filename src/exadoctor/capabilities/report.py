"""Assembles and renders the `exadoctor capabilities` report."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from exadoctor.capabilities.models import Capability
from exadoctor.capabilities.sources import EXCLUDED_INTERNAL_DERIVED_CAPABILITIES


@dataclass
class CapabilityReport:
    database_version: str | None
    capabilities: list[Capability]
    excluded_internal: tuple[str, ...] = field(default=EXCLUDED_INTERNAL_DERIVED_CAPABILITIES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "database_version": self.database_version,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "excluded_internal_derived_capabilities": {
                name: {
                    "available": False,
                    "reason": (
                        "Excluded by policy: $EXA_* internal sources are out of scope "
                        "for this build. See docs/internal-interface-policy.md."
                    ),
                }
                for name in self.excluded_internal
            },
        }

    def render_text(self) -> str:
        lines = ["EXADOCTOR CAPABILITY REPORT", ""]
        if self.database_version:
            lines.append(f"Database version: {self.database_version}")
            lines.append("")

        lines.append("PUBLIC SOURCES")
        for cap in self.capabilities:
            status = "AVAILABLE" if cap.available else "UNAVAILABLE"
            data_note = ""
            if cap.available and cap.data_available is not None:
                data_note = " (data present)" if cap.data_available else " (no rows in window)"
            lines.append(f"  {cap.id:<28} {status}{data_note}")
            if not cap.available and cap.reason:
                lines.append(f"    reason: {cap.reason}")
        lines.append("")

        lines.append("DERIVED DEEP DIAGNOSTICS (excluded by policy)")
        for name in self.excluded_internal:
            lines.append(f"  {name:<28} NOT_AVAILABLE (requires $EXA_*, out of scope)")

        return "\n".join(lines)


def build_report(database_version: str | None, capabilities: list[Capability]) -> CapabilityReport:
    return CapabilityReport(database_version=database_version, capabilities=capabilities)
