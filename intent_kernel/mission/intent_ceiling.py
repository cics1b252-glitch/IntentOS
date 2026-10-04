"""J1 — Intent Authority Ceiling contract.

Frozen, immutable, digest-bound authority ceiling for plan actions.
PLANNER != AUTHORITY: the ceiling is the lattice's root input, not a
parallel engine. The planner may propose; the ceiling disposes.

Canonical invariant:
    PLAN_ACTION <= VALID_INTENT_AUTHORITY

Every planned action must independently satisfy the intent ceiling.
One valid action must not authorize another.

Fail-closed semantics:
- Empty/default ceiling → DENY (no permissive legacy semantics)
- Temporal dependency + missing/invalid clock → DENY
- Mutable collection inputs → normalized to tuples
- String allowlist → rejected (no substring membership)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from intent_kernel.mission.delegation import (
    RISK_SEVERITY,
    SIDE_EFFECT_SEVERITY,
    is_expired,
)


def _normalize_str_tuple(value: Any, label: str) -> Tuple[str, ...]:
    """Normalize a collection to a tuple of strings, fail-closed."""
    if value is None:
        return ()
    if isinstance(value, str):
        raise ValueError(f"{label} must not be a string (use a tuple/list)")
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError(f"{label} must be a collection of strings")
    result = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{label} items must be strings")
        result.append(item)
    return tuple(result)


@dataclass(frozen=True)
class IntentCeiling:
    """Immutable intent authority ceiling.

    All dimensions optional-per-dimension. An authority-bearing ceiling
    must contain at least one explicit constraining dimension.
    """

    allow_capabilities: Tuple[str, ...] = ()
    allowed_operations: Tuple[str, ...] = ()
    target_scope: Tuple[str, ...] = ()
    max_risk_level: str = ""
    max_side_effect: str = ""
    require_verification: Optional[bool] = None
    valid_from: str = ""
    valid_until: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "allow_capabilities", _normalize_str_tuple(self.allow_capabilities, "allow_capabilities"))
        object.__setattr__(self, "allowed_operations", _normalize_str_tuple(self.allowed_operations, "allowed_operations"))
        object.__setattr__(self, "target_scope", _normalize_str_tuple(self.target_scope, "target_scope"))
        if self.max_risk_level and self.max_risk_level not in RISK_SEVERITY:
            raise ValueError(f"unknown risk level: {self.max_risk_level}")
        if self.max_side_effect and self.max_side_effect not in SIDE_EFFECT_SEVERITY:
            raise ValueError(f"unknown side-effect level: {self.max_side_effect}")
        if self.require_verification is not None and not isinstance(self.require_verification, bool):
            raise ValueError("require_verification must be bool or None")

    @property
    def is_constraining(self) -> bool:
        """True if at least one explicit constraining dimension is present."""
        return bool(
            self.allow_capabilities
            or self.allowed_operations
            or self.target_scope
            or self.max_risk_level
            or self.max_side_effect
            or self.require_verification is not None
            or self.valid_from
            or self.valid_until
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allow_capabilities": list(self.allow_capabilities),
            "allowed_operations": list(self.allowed_operations),
            "target_scope": list(self.target_scope),
            "max_risk_level": self.max_risk_level,
            "max_side_effect": self.max_side_effect,
            "require_verification": self.require_verification,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IntentCeiling":
        return cls(
            allow_capabilities=_normalize_str_tuple(data.get("allow_capabilities"), "allow_capabilities"),
            allowed_operations=_normalize_str_tuple(data.get("allowed_operations"), "allowed_operations"),
            target_scope=_normalize_str_tuple(data.get("target_scope"), "target_scope"),
            max_risk_level=str(data.get("max_risk_level", "") or ""),
            max_side_effect=str(data.get("max_side_effect", "") or ""),
            require_verification=data.get("require_verification"),
            valid_from=str(data.get("valid_from", "") or ""),
            valid_until=str(data.get("valid_until", "") or ""),
        )


def proof_plan_action_against_ceiling(
    ceiling: Optional[IntentCeiling],
    *,
    capability: str,
    operation: str = "",
    target: str = "",
    risk_level: str = "",
    side_effect: str = "",
    verification_required: bool = False,
    now_iso: str = "",
) -> Tuple[bool, str]:
    """Pure fail-closed proof: PLAN_DIMENSION <= INTENT_CEILING_DIMENSION.

    Returns (True, "") if the plan action is within the ceiling.
    Returns (False, reason) if any dimension exceeds the ceiling.

    Absent ceiling (None) → DENY.
    Empty/default ceiling → DENY (no permissive legacy semantics).
    Temporal dependency + missing/invalid clock → DENY.
    """
    if ceiling is None:
        return False, "intent-ceiling-absent"

    if not ceiling.is_constraining:
        return False, "intent-ceiling-empty"

    # Capability allowlist
    if ceiling.allow_capabilities and capability not in ceiling.allow_capabilities:
        return False, "capability-escalation"

    # Operation scope
    if ceiling.allowed_operations and operation and operation not in ceiling.allowed_operations:
        return False, "operation-escalation"

    # Target scope
    if ceiling.target_scope and target and target not in ceiling.target_scope:
        return False, "target-escalation"

    # Risk ceiling
    if ceiling.max_risk_level and risk_level:
        if risk_level not in RISK_SEVERITY:
            return False, "unknown-risk-level"
        if RISK_SEVERITY[risk_level] > RISK_SEVERITY[ceiling.max_risk_level]:
            return False, "risk-escalation"

    # Side-effect ceiling
    if ceiling.max_side_effect and side_effect:
        if side_effect not in SIDE_EFFECT_SEVERITY:
            return False, "unknown-side-effect-level"
        if SIDE_EFFECT_SEVERITY[side_effect] > SIDE_EFFECT_SEVERITY[ceiling.max_side_effect]:
            return False, "side-effect-escalation"

    # Verification requirement: plan must not weaken ceiling requirement
    if ceiling.require_verification is True and not verification_required:
        return False, "verification-weakened"

    # Expiry / validity window — fail closed on missing/invalid clock
    ok, reason = _check_temporal_validity(ceiling, now_iso)
    if not ok:
        return False, reason

    return True, ""


def _check_temporal_validity(
    ceiling: IntentCeiling,
    now_iso: str = "",
) -> Tuple[bool, str]:
    """Pure temporal validity check for an IntentCeiling.

    Returns (True, "") if ceiling has no temporal constraints or is currently valid.
    Returns (False, reason) if temporal constraints exist and are violated or unevaluable.

    This is a pure function: no authority grant, no mutation, no capability inspection.
    """
    has_temporal = bool(ceiling.valid_from or ceiling.valid_until)
    if not has_temporal:
        return True, ""

    if not now_iso:
        return False, "ceiling-temporal-unknown"

    # Validate clock format (ISO-8601 check)
    from intent_kernel.time_utils import utc_iso
    normalized = utc_iso(now_iso, fallback_now=False)
    if normalized is None:
        return False, "ceiling-temporal-invalid"

    if ceiling.valid_until:
        if is_expired(ceiling.valid_until, normalized):
            return False, "ceiling-expired"
    if ceiling.valid_from:
        if normalized < ceiling.valid_from:
            return False, "ceiling-not-yet-valid"

    return True, ""
