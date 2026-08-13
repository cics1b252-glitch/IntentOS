"""Canonical, non-sensitive characterization of compatibility execution paths."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, MutableMapping


@dataclass(frozen=True, slots=True)
class CompatibilityTrace:
    """Evidence that a subordinate compatibility component participated.

    The trace intentionally carries no request text, memory values, credentials,
    or provider payloads.  It characterizes authority, not user data.
    """

    compatibility_path_used: bool
    compatibility_component: str
    reason: str
    canonical_alternative_missing: str | None
    deprecation_candidate: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compatibility_trace(
    component: str,
    reason: str,
    *,
    canonical_alternative_missing: str | None,
    deprecation_candidate: bool = True,
) -> CompatibilityTrace:
    """Create the one standard compatibility trace contract."""
    return CompatibilityTrace(
        compatibility_path_used=True,
        compatibility_component=component,
        reason=reason,
        canonical_alternative_missing=canonical_alternative_missing,
        deprecation_candidate=deprecation_candidate,
    )


def attach_compatibility_trace(
    target: MutableMapping[str, Any], trace: CompatibilityTrace
) -> MutableMapping[str, Any]:
    """Attach a trace without allowing compatibility to replace canonical data."""
    target.setdefault("compatibility_path_used", True)
    target.setdefault("compatibility_trace", trace.to_dict())
    return target
