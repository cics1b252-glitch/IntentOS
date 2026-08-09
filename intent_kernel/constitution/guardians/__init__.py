"""Guardians — executable Constitution validators for the Intent OS Kernel.

Each Guardian protects a constitutional principle by validating
Knowledge Events and system actions against it.

Based on Constitution v1.1 directive (2026-07-23).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Guardian Protocol — every Guardian must implement this
# ---------------------------------------------------------------------------

@runtime_checkable
class Guardian(Protocol):
    """Base protocol for all Constitution Guardians.

    Every Guardian:
    - Has a name and description
    - Validates events/actions against its principle
    - Returns a GuardianVerdict (allowed/blocked/flagged)
    - Can be observed by the Monitor (provides status)
    """

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def principle(self) -> str:
        """Which constitutional principle this Guardian protects."""
        ...

    def validate(self, event: dict[str, Any], context: dict[str, Any] | None = None) -> GuardianVerdict:
        """Validate an event/action against this Guardian's principle."""
        ...

    def status(self) -> dict[str, Any]:
        """Return status for the Monitor."""
        ...


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

@dataclass
class GuardianVerdict:
    """Result of a Guardian validation."""
    guardian: str           # Guardian name
    decision: str           # 'allowed' | 'blocked' | 'flagged'
    reason: str
    details: dict | None = None


# ---------------------------------------------------------------------------
# Guardian Registry
# ---------------------------------------------------------------------------

class GuardianRegistry:
    """Central registry of all Guardians.

    The Kernel loads all Guardians at startup.
    No module can be loaded if any Guardian blocks it.
    """

    def __init__(self):
        self._guardians: dict[str, Guardian] = {}

    def register(self, guardian: Guardian) -> None:
        """Register a Guardian."""
        self._guardians[guardian.name] = guardian

    def get(self, name: str) -> Guardian | None:
        return self._guardians.get(name)

    def validate_all(self, event: dict[str, Any], context: dict[str, Any] | None = None) -> list[GuardianVerdict]:
        """Run all Guardians against an event. Returns list of verdicts."""
        verdicts = []
        for guardian in self._guardians.values():
            verdict = guardian.validate(event, context)
            verdicts.append(verdict)
        return verdicts

    def resolve(self, verdicts: list[GuardianVerdict]) -> GuardianVerdict:
        """Resolve multiple verdicts into a single decision.

        Priority: blocked > flagged > allowed
        """
        blocked = [v for v in verdicts if v.decision == "blocked"]
        flagged = [v for v in verdicts if v.decision == "flagged"]

        if blocked:
            reasons = " | ".join(v.reason for v in blocked)
            guardians = [v.guardian for v in blocked]
            return GuardianVerdict(
                guardian="registry",
                decision="blocked",
                reason=reasons,
                details={"violating_guardians": guardians},
            )

        if flagged:
            reasons = " | ".join(v.reason for v in flagged)
            guardians = [v.guardian for v in flagged]
            return GuardianVerdict(
                guardian="registry",
                decision="flagged",
                reason=reasons,
                details={"flagging_guardians": guardians},
            )

        return GuardianVerdict(guardian="registry", decision="allowed", reason="All Guardians passed.")

    def status(self) -> dict[str, Any]:
        """Return status of all Guardians for the Monitor."""
        return {
            "count": len(self._guardians),
            "guardians": {
                name: g.status()
                for name, g in self._guardians.items()
            },
        }

    @property
    def names(self) -> list[str]:
        return list(self._guardians.keys())
