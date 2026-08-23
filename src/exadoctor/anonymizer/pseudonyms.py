"""Deterministic pseudonym generation for ExaDoctor's anonymizer package.

Roadmap section 12.2 / Milestone 16 require that a "support-shareable"
Snapshot replace identifying information with pseudonyms that are "stable
within a report": every occurrence of the same real value, anywhere in one
Snapshot, must map to the same pseudonym.

Design choice -- first-seen-order sequential numbering, not a hash:
    A pseudonym is built as ``f"{PREFIX}_{n}"`` where ``n`` is 1 for the
    first distinct real value seen in a category, 2 for the second, and so
    on. Two alternatives were considered and rejected:

    * Hash-based pseudonyms (e.g. ``"USER_" + sha256(real_value)[:8]``) are
      deterministic *within* a run too, but they are also deterministic
      *across* runs/reports for any value that happens to be the same
      string in two different customers' databases (every deployment with
      a session for user "SYS" would get an identical pseudonym for it).
      The roadmap only requires stability "within a report" -- it does not
      ask for, and arguably should avoid, a scheme that lets two different
      customers' anonymized reports be correlated with each other by
      matching hashes. Sequential numbering, scoped to one
      `PseudonymMapper` instance (one anonymization run), avoids that
      cross-report linkage entirely.
    * Random pseudonyms would also satisfy "stable within a report" (the
      mapping dict still guarantees consistent reuse within the run), but
      are harder to read/debug ("who is USER_af9c2b?") and non-reproducible
      run to run, which only makes tests and manual verification harder
      for no real benefit.

    Sequential numbering also simply reads better in a shared report:
    "USER_1 ran this query, USER_2 ran that one" is easier to follow than
    opaque hex suffixes.

Categories are namespaced: a `PseudonymMapper` keys its internal table by
``(category, real_value)``, so a host and a user that happen to share the
same real string never collide and never share a pseudonym sequence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Categories this package's anonymizer actually applies today -- see
# anonymizer.py's module docstring for exactly which Snapshot fields feed
# each one. `PseudonymMapper.pseudonym_for` accepts any category string,
# not just these: an unrecognized category falls back to its own
# uppercased name as the prefix, so a future identity kind (e.g. once a
# collector adds a schema/table field -- neither exists in the Snapshot
# model yet) can reuse this mapper without changes here.
CATEGORY_USER = "user"
CATEGORY_HOST = "host"
CATEGORY_CLUSTER = "cluster"
CATEGORY_SCHEMA = "schema"
CATEGORY_TABLE = "table"

_DEFAULT_PREFIXES: dict[str, str] = {
    CATEGORY_USER: "USER",
    CATEGORY_HOST: "HOST",
    CATEGORY_CLUSTER: "CLUSTER",
    CATEGORY_SCHEMA: "SCHEMA",
    CATEGORY_TABLE: "TABLE",
}


@dataclass
class PseudonymMapper:
    """Stable, in-memory real-value -> pseudonym table for one anonymization run.

    Not persisted anywhere by this class. A caller who wants to keep the
    mapping (e.g. to de-anonymize a specific value later while triaging a
    shared report) is responsible for storing it themselves --
    see `anonymizer.AnonymizationResult.mapping`.
    """

    _pseudonyms: dict[tuple[str, str], str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    def pseudonym_for(self, category: str, real_value: str) -> str:
        """Return the stable pseudonym for `real_value` within `category`.

        The first call for a given (category, real_value) pair mints a new
        pseudonym in first-seen order; every subsequent call with the same
        pair returns that same pseudonym.
        """
        key = (category, real_value)
        existing = self._pseudonyms.get(key)
        if existing is not None:
            return existing

        self._counters[category] = self._counters.get(category, 0) + 1
        prefix = _DEFAULT_PREFIXES.get(category, category.upper())
        pseudonym = f"{prefix}_{self._counters[category]}"
        self._pseudonyms[key] = pseudonym
        return pseudonym

    def mapping(self) -> dict[str, dict[str, str]]:
        """Return the real-value -> pseudonym table, grouped by category.

        Returned as a fresh dict (not a live view), so a caller can hold on
        to it without risk of it changing under them as this mapper is
        used further.
        """
        grouped: dict[str, dict[str, str]] = {}
        for (category, real_value), pseudonym in self._pseudonyms.items():
            grouped.setdefault(category, {})[real_value] = pseudonym
        return grouped
