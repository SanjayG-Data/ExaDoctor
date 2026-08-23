"""Finding and Evidence models (roadmap sections 5.4, 6.2, 6.4).

Lives under `exadoctor.models`, not `exadoctor.rules`, even though rules
are what produce Findings: `Snapshot.findings` holds them directly, and
having the dependency point one way (rules depends on models, never the
reverse) avoids a circular import between the two packages.

Design note on `status` vs `severity`: the roadmap defines one status
vocabulary (PASS/INFO/WARNING/CRITICAL/NOT_EVALUATED/NOT_APPLICABLE, section
5.4) and section 8.3's severity discipline ("prefer INFO", "use WARNING
only when...", "use CRITICAL sparingly") uses that same vocabulary to talk
about severity -- the roadmap never defines a second, distinct severity
scale. Rather than invent one, `severity` mirrors `status` here: it exists
as its own field (per the section 6.4 contract) but always carries the same
value as `status`. If a genuinely separate severity scale is needed later
(e.g. numeric scoring), it can be introduced without breaking this field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class FindingStatus(str, Enum):
    PASS = "PASS"
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    NOT_EVALUATED = "NOT_EVALUATED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


@dataclass
class Evidence:
    source: str
    stability: str
    metric: str
    value: Any
    unit: str | None
    timestamp: datetime | None
    context: str | None = None
    session_id: int | None = None
    stmt_id: int | None = None
    part_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "stability": self.stability,
            "metric": self.metric,
            "value": _json_safe_value(self.value),
            "unit": self.unit,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "context": self.context,
            "session_id": self.session_id,
            "stmt_id": self.stmt_id,
            "part_id": self.part_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Evidence:
        return cls(
            source=data["source"],
            stability=data["stability"],
            metric=data["metric"],
            value=data["value"],
            unit=data["unit"],
            timestamp=datetime.fromisoformat(data["timestamp"]) if data["timestamp"] else None,
            context=data["context"],
            session_id=data["session_id"],
            stmt_id=data["stmt_id"],
            part_id=data["part_id"],
        )


@dataclass
class Finding:
    id: str
    title: str
    category: str
    status: FindingStatus
    summary: str
    severity: FindingStatus | None = None  # see module docstring; defaults to `status` in __post_init__
    evidence: list[Evidence] = field(default_factory=list)
    recommendation: str | None = None
    confidence: str = "MEDIUM"  # "LOW" | "MEDIUM" | "HIGH"
    requirements: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    documentation: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.severity is None:
            self.severity = self.status

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "status": self.status.value,
            "severity": self.severity.value if self.severity else self.status.value,
            "summary": self.summary,
            "evidence": [e.to_dict() for e in self.evidence],
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "requirements": list(self.requirements),
            "limitations": list(self.limitations),
            "documentation": list(self.documentation),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        return cls(
            id=data["id"],
            title=data["title"],
            category=data["category"],
            status=FindingStatus(data["status"]),
            severity=FindingStatus(data["severity"]) if data.get("severity") else None,
            summary=data["summary"],
            evidence=[Evidence.from_dict(e) for e in data["evidence"]],
            recommendation=data["recommendation"],
            confidence=data["confidence"],
            requirements=list(data["requirements"]),
            limitations=list(data["limitations"]),
            documentation=list(data["documentation"]),
        )


def not_evaluated(
    rule_id: str,
    title: str,
    category: str,
    reason: str,
    requirements: list[str] | None = None,
) -> Finding:
    """Standard NOT_EVALUATED finding -- missing evidence never becomes PASS."""
    return Finding(
        id=rule_id,
        title=title,
        category=category,
        status=FindingStatus.NOT_EVALUATED,
        summary=f"Not evaluated: {reason}",
        confidence="LOW",
        requirements=requirements or [],
        limitations=[reason],
    )
