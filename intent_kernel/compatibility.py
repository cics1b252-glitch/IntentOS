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
    entry_point: str
    canonical_alternative_missing: str | None
    deprecation_candidate: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compatibility_trace(
    component: str,
    reason: str,
    *,
    entry_point: str = "explicit_compatibility_boundary",
    canonical_alternative_missing: str | None,
    deprecation_candidate: bool = True,
) -> CompatibilityTrace:
    """Create the one standard compatibility trace contract."""
    return CompatibilityTrace(
        compatibility_path_used=True,
        compatibility_component=component,
        reason=reason,
        entry_point=entry_point,
        canonical_alternative_missing=canonical_alternative_missing,
        deprecation_candidate=deprecation_candidate,
    )


def attach_compatibility_trace(
    target: MutableMapping[str, Any], trace: CompatibilityTrace
) -> MutableMapping[str, Any]:
    """Record observed participation without reconstructing it from heuristics."""
    event = trace.to_dict()
    events = target.setdefault("compatibility_traces", [])
    if event not in events:
        events.append(event)
    target["compatibility_path_used"] = bool(events)
    # Stable single-event projection for protocol consumers being migrated.
    target["compatibility_trace"] = events[0]
    return target
