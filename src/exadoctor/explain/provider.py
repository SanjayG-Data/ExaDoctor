"""AI explanation layer interface (roadmap Milestone 21).

DESIGN PRINCIPLE (from the roadmap): AI explains deterministic findings. AI
does not create the underlying diagnosis. Every provider must uphold:
- Receives only structured `Finding` data -- never database access.
- May summarize, prioritize, translate, or explain Exasol terminology.
- May propose investigation questions, explicitly marked as suggestions.
- Must NEVER alter severity, invent evidence, or execute anything.
- `provider=None` (or a failing provider) must never break the core tool --
  `exadoctor scan`/`query` always work without any AI layer configured.
"""

from __future__ import annotations

from typing import Protocol

from exadoctor.models.finding import Finding


class ExplanationProvider(Protocol):
    def explain(self, findings: list[Finding]) -> str: ...
