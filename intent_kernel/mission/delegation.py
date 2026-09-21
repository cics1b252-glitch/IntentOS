"""M33.2B — Governed non-escalating delegation: pure derivation model.

Core invariant:

    AUTHORITY(CHILD) ⊆ AUTHORITY(PARENT)

Delegation narrows authority. Delegation never manufactures or expands
authority. Delegation is DERIVED authority: every grant is rooted in an
already-authorized durable action, and every use re-proves the derivation.

Pure logic only. This module contains:

- no store implementation,
- no RRM imports,
- no runtime objects,
- no credentials,
- no tokens.

All functions are total over plain JSON-safe values and fail closed.
Time is always an explicit ``now_iso`` parameter (ISO-8601 UTC, lexicographic
comparison — the same convention as confirmation TTL expiry); nothing here
reads a clock, so every proof is deterministic and replayable in tests.

Scope model (V1):

- Delegates are governed AGENTS only (agent identity + governed
  registration). Tool delegation is deferred: ToolResource carries no
  equivalent governed registration identity.
- Targets are exact typed ID allowlists. No wildcards. No hierarchy.
- Constraints are mechanically comparable typed fields only
  (risk ceiling, timeout ceiling, verification requirement,
  side-effect ceiling). Arbitrary dict/string/predicate constraints are
  NOT supported: free-form constraints cannot support safe subset
  comparison, so they are rejected, never guessed.
- Delegation is mission-scoped: parent and child live in the same
  mission record. Cross-mission delegation is deferred and structurally
  rejected (parent_mission_id must equal the child mission).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Tuple


class DelegationError(ValueError):
    """A delegation derivation or validation failed closed."""


#: Maximum delegation chain depth (edges from the root action). Deeper
#: chains fail closed at creation and at enforcement. Bounds the chain
#: walk, the RRM liveness loop, and the review surface.
MAX_DELEGATION_DEPTH = 4


#: Ordered risk severity. Child ceiling must be <= parent effective level.
RISK_SEVERITY: Dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


#: Ordered side-effect severity. Mirrors SideEffectLevel values exactly.
SIDE_EFFECT_SEVERITY: Dict[str, int] = {
    "NONE": 0,
    "LOCAL_REVERSIBLE": 1,
    "LOCAL_IRREVERSIBLE": 2,
    "EXTERNAL_REVERSIBLE": 3,
    "EXTERNAL_IRREVERSIBLE": 4,
}


class DelegationState(str, Enum):
    """Durable delegation grant lifecycle.

    NONE marks "no delegation on this action". ACTIVE grants may
    authorize; REVOKED grants never do again. Expiry is NOT a stored
    state: it is derived from expires_at at every validation, so no
    writer must flip it and a stale process can never resurrect one.
    """

    NONE = "NONE"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class DelegatedResource:
    """One exact resource triple a delegate may invoke.

    Same shape as ExecutionPrecondition's resource identity, expressed
    locally so this module imports nothing outside the standard library.
    """

    resource_id: str
    governed_registration_id: str = ""
    generation: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise DelegationError("DelegatedResource.resource_id must be non-empty")
        if not isinstance(self.governed_registration_id, str):
            raise DelegationError(
                "DelegatedResource.governed_registration_id must be a string"
            )
        if not isinstance(self.generation, int) or isinstance(self.generation, bool):
            raise DelegationError("DelegatedResource.generation must be an int")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "governed_registration_id": self.governed_registration_id,
            "generation": self.generation,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DelegatedResource":
        if not isinstance(data, Mapping):
            raise DelegationError("DelegatedResource must be a mapping")
        try:
            return cls(
                resource_id=data["resource_id"],
                governed_registration_id=data.get("governed_registration_id", ""),
                generation=data.get("generation", 0),
            )
        except KeyError as exc:
            raise DelegationError(
                f"DelegatedResource missing field: {exc}"
            ) from exc


@dataclass(frozen=True, slots=True)
class DelegationGrant:
    """One non-escalating delegation grant (pure value object).

    Field names match the durable ``delegation_*`` record fields exactly,
    so no translation layer exists between this model, the authority, the
    store, and enforcement — one vocabulary end to end.

    Identity: delegation_id is minted by the authority as
    ``dlg_<uuid4hex>`` — never caller-supplied. Lineage: parent_* points
    at the authorizing durable action; root_* pins the original ceiling
    so depth cannot dilute it. Scope: exact capability names, exact
    resource triples, exact target IDs. Ceilings: "" / 0 / None mean
    "inherit parent effective" and are legal only on nested grants;
    root grants (parent is a plain authorized action) must be explicit.
    """

    delegation_id: str
    delegation_parent_mission_id: str
    delegation_parent_action_id: str
    delegation_parent_delegation_id: str = ""
    delegation_root_mission_id: str = ""
    delegation_root_action_id: str = ""
    delegation_root_governed_registration_id: str = ""
    delegation_root_generation: int = 0
    delegation_delegator_grid: str = ""
    delegation_delegator_agent_id: str = ""
    delegation_delegate_agent_id: str = ""
    delegation_delegate_grid: str = ""
    delegation_allowed_capabilities: Tuple[str, ...] = ()
    delegation_allowed_resources: Tuple[DelegatedResource, ...] = ()
    delegation_allowed_targets: Tuple[str, ...] = ()
    delegation_max_risk_level: str = ""
    delegation_max_timeout_seconds: float = 0.0
    delegation_require_verification: Optional[bool] = None
    delegation_max_side_effect: str = ""
    delegation_created_at: str = ""
    delegation_expires_at: str = ""
    delegation_state: DelegationState = DelegationState.ACTIVE
    delegation_revoked_at: str = ""
    delegation_revoke_reason: str = ""

    def __post_init__(self) -> None:
        for label in (
            "delegation_id",
            "delegation_parent_mission_id",
            "delegation_parent_action_id",
            "delegation_root_mission_id",
            "delegation_root_action_id",
            "delegation_delegator_grid",
            "delegation_delegate_agent_id",
        ):
            value = getattr(self, label)
            if not isinstance(value, str) or not value.strip():
                raise DelegationError(f"DelegationGrant.{label} must be non-empty")
        for label in (
            "delegation_parent_delegation_id",
            "delegation_root_governed_registration_id",
            "delegation_delegator_agent_id",
            "delegation_delegate_grid",
            "delegation_max_risk_level",
            "delegation_max_side_effect",
            "delegation_created_at",
            "delegation_expires_at",
            "delegation_revoked_at",
            "delegation_revoke_reason",
        ):
            if not isinstance(getattr(self, label), str):
                raise DelegationError(f"DelegationGrant.{label} must be a string")
        if not isinstance(self.delegation_root_generation, int) or isinstance(
            self.delegation_root_generation, bool
        ):
            raise DelegationError(
                "DelegationGrant.delegation_root_generation must be an int"
            )
        if not self.delegation_allowed_capabilities:
            raise DelegationError(
                "DelegationGrant.delegation_allowed_capabilities must be non-empty"
            )
        if not self.delegation_allowed_resources:
            raise DelegationError(
                "DelegationGrant.delegation_allowed_resources must be non-empty: an "
                "empty resource scope would leave the child binding "
                "uncompared against the parent (escalation hole)"
            )
        for cap in self.delegation_allowed_capabilities:
            if not isinstance(cap, str) or not cap.strip():
                raise DelegationError(
                    "DelegationGrant.delegation_allowed_capabilities items must be "
                    "non-empty strings"
                )
        object.__setattr__(
            self,
            "delegation_allowed_capabilities",
            tuple(self.delegation_allowed_capabilities),
        )
        resources: List[DelegatedResource] = []
        for item in self.delegation_allowed_resources or ():
            if isinstance(item, Mapping):
                item = DelegatedResource.from_dict(item)
            if not isinstance(item, DelegatedResource):
                raise DelegationError(
                    "DelegationGrant.delegation_allowed_resources items must be "
                    "DelegatedResource"
                )
            resources.append(item)
        object.__setattr__(self, "delegation_allowed_resources", tuple(resources))
        for target in self.delegation_allowed_targets or ():
            if not isinstance(target, str) or not target.strip():
                raise DelegationError(
                    "DelegationGrant.delegation_allowed_targets items must be "
                    "non-empty strings"
                )
        object.__setattr__(
            self, "delegation_allowed_targets", tuple(self.delegation_allowed_targets or ())
        )
        if (
            self.delegation_max_risk_level
            and self.delegation_max_risk_level not in RISK_SEVERITY
        ):
            raise DelegationError(
                "DelegationGrant.delegation_max_risk_level unknown: "
                f"{self.delegation_max_risk_level!r}"
            )
        if not isinstance(self.delegation_max_timeout_seconds, (int, float)) or isinstance(
            self.delegation_max_timeout_seconds, bool
        ):
            raise DelegationError(
                "DelegationGrant.delegation_max_timeout_seconds must be numeric"
            )
        if self.delegation_require_verification is not None and not isinstance(
            self.delegation_require_verification, bool
        ):
            raise DelegationError(
                "DelegationGrant.delegation_require_verification must be a bool or None"
            )
        if (
            self.delegation_max_side_effect
            and self.delegation_max_side_effect not in SIDE_EFFECT_SEVERITY
        ):
            raise DelegationError(
                "DelegationGrant.delegation_max_side_effect unknown: "
                f"{self.delegation_max_side_effect!r}"
            )
        if not isinstance(self.delegation_state, DelegationState):
            raise DelegationError(
                "DelegationGrant.delegation_state must be a DelegationState"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "delegation_id": self.delegation_id,
            "delegation_parent_mission_id": self.delegation_parent_mission_id,
            "delegation_parent_action_id": self.delegation_parent_action_id,
            "delegation_parent_delegation_id": (
                self.delegation_parent_delegation_id
            ),
            "delegation_root_mission_id": self.delegation_root_mission_id,
            "delegation_root_action_id": self.delegation_root_action_id,
            "delegation_root_governed_registration_id": (
                self.delegation_root_governed_registration_id
            ),
            "delegation_root_generation": self.delegation_root_generation,
            "delegation_delegator_grid": self.delegation_delegator_grid,
            "delegation_delegator_agent_id": self.delegation_delegator_agent_id,
            "delegation_delegate_agent_id": self.delegation_delegate_agent_id,
            "delegation_delegate_grid": self.delegation_delegate_grid,
            "delegation_allowed_capabilities": list(
                self.delegation_allowed_capabilities
            ),
            "delegation_allowed_resources": [
                r.to_dict() for r in self.delegation_allowed_resources
            ],
            "delegation_allowed_targets": list(self.delegation_allowed_targets),
            "delegation_max_risk_level": self.delegation_max_risk_level,
            "delegation_max_timeout_seconds": self.delegation_max_timeout_seconds,
            "delegation_require_verification": self.delegation_require_verification,
            "delegation_max_side_effect": self.delegation_max_side_effect,
            "delegation_created_at": self.delegation_created_at,
            "delegation_expires_at": self.delegation_expires_at,
            "delegation_state": self.delegation_state.value,
            "delegation_revoked_at": self.delegation_revoked_at,
            "delegation_revoke_reason": self.delegation_revoke_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DelegationGrant":
        if not isinstance(data, Mapping):
            raise DelegationError("DelegationGrant must be a mapping")
        d = dict(data)
        state_raw = d.get("delegation_state", DelegationState.ACTIVE.value)
        try:
            d["delegation_state"] = (
                state_raw
                if isinstance(state_raw, DelegationState)
                else DelegationState(state_raw)
            )
        except ValueError as exc:
            raise DelegationError(
                f"DelegationGrant.delegation_state unknown: {state_raw!r}"
            ) from exc
        try:
            return cls(**d)
        except TypeError as exc:
            raise DelegationError(
                f"DelegationGrant fields mismatch: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Small pure provers
# ---------------------------------------------------------------------------

def is_expired(expires_at: str, now_iso: str) -> bool:
    """Expiry is time-relative and derived, never stored as state."""
    return bool(expires_at) and bool(now_iso) and now_iso > expires_at


def capability_subset(child_caps: Any, parent_caps: Any) -> bool:
    """Exact-name set inclusion. No wildcards exist in V1."""
    try:
        return bool(child_caps) and set(child_caps) <= set(parent_caps)
    except TypeError:
        return False


def _triple(item: Mapping[str, Any]) -> Tuple[str, str, int]:
    return (
        str(item.get("resource_id", "")),
        str(item.get("governed_registration_id", "")),
        int(item.get("generation", 0) or 0),
    )


def resource_subset(child: Any, parent: Any) -> bool:
    """Exact-triple set inclusion over (resource_id, grid, generation)."""
    try:
        child_set = {_triple(r) for r in (child or ())}
        parent_set = {_triple(r) for r in (parent or ())}
    except (TypeError, ValueError, AttributeError):
        return False
    return bool(child_set) and child_set <= parent_set


def target_subset(child_targets: Any, parent_targets: Any) -> bool:
    """Exact-ID set inclusion. An unrestricted dimension (empty parent
    set) admits any explicit child set — other dimensions still bind."""
    try:
        child_set = set(child_targets or ())
        parent_set = set(parent_targets or ())
    except TypeError:
        return False
    if not parent_set:
        return True
    return bool(child_set) and child_set <= parent_set


def lifetime_subset(child_expiry: str, parent_expiry: str) -> bool:
    """Child lifetime must not exceed parent lifetime. Empty means none;
    a child expiry is allowed only under an unbounded parent when the
    parent itself carries none... no: when the parent carries an expiry,
    the child must carry one no later. An unbounded parent admits any
    child lifetime (including none)."""
    if not isinstance(child_expiry, str) or not isinstance(parent_expiry, str):
        return False
    if not parent_expiry:
        return True
    return bool(child_expiry) and child_expiry <= parent_expiry


def _severity(table: Mapping[str, int], level: str) -> Optional[int]:
    if not isinstance(level, str) or level not in table:
        return None
    return table[level]


def risk_allows(child_level: str, parent_level: str) -> bool:
    """Child risk ceiling must be equal-or-stricter (lower-or-equal)."""
    child = _severity(RISK_SEVERITY, child_level)
    parent = _severity(RISK_SEVERITY, parent_level)
    if child is None or parent is None:
        return False
    return child <= parent


def timeout_allows(child_timeout: Any, parent_timeout: Any) -> bool:
    """Child timeout ceiling must be equal-or-stricter (lower-or-equal).
    Non-positive means unbounded; unbounded child under a bounded parent
    is rejected."""
    if (
        not isinstance(child_timeout, (int, float))
        or isinstance(child_timeout, bool)
        or not isinstance(parent_timeout, (int, float))
        or isinstance(parent_timeout, bool)
    ):
        return False
    if parent_timeout <= 0:
        return True
    return 0 < child_timeout <= parent_timeout


def verification_allows(child_required: Any, parent_required: Any) -> bool:
    """Verification may only be added, never removed, down a chain."""
    if not isinstance(parent_required, bool) or (
        child_required is not None and not isinstance(child_required, bool)
    ):
        return False
    if parent_required:
        return child_required is True
    return True


def side_effect_allows(child_level: str, parent_level: str) -> bool:
    """Child side-effect ceiling must be equal-or-stricter."""
    child = _severity(SIDE_EFFECT_SEVERITY, child_level)
    parent = _severity(SIDE_EFFECT_SEVERITY, parent_level)
    if child is None or parent is None:
        return False
    return child <= parent


# ---------------------------------------------------------------------------
# Edge proof: child grant ⊆ parent view
# ---------------------------------------------------------------------------

def resolve_parent_view(
    parent_action: Mapping[str, Any],
    parent_plan_capability: str,
    parent_grant: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Resolve the effective authority view a child must narrow.

    Root edge (parent carries no grant): capabilities and resources come
    from the parent action's own durable binding; targets are
    granted-bounded (no parent set to narrow); ceilings/expiry are None,
    meaning the child grant must carry them explicitly.
    Nested edge: every dimension narrows against the parent grant.
    Inherit-empty child values resolve against the parent effective
    values inside prove_edge(); stored grants are always explicit
    (the authority resolves inheritance at creation).
    """
    view: Dict[str, Any] = {
        "capabilities": set(),
        "resources": set(),
        "targets": None,
        "ceilings": None,
        "expiry": None,
    }
    if parent_grant is None:
        if parent_plan_capability:
            view["capabilities"] = {str(parent_plan_capability)}
        grid = str(parent_action.get("expected_governed_registration_id", "") or "")
        gen = parent_action.get("expected_resource_generation", 0)
        try:
            gen = int(gen or 0)
        except (TypeError, ValueError):
            gen = 0
        if grid:
            view["resources"] = {(str(parent_action.get("expected_resource_id", "") or ""), grid, gen)}
        return view
    try:
        view["capabilities"] = set(
            parent_grant.get("delegation_allowed_capabilities", ()) or ()
        )
        view["resources"] = {
            _triple(r)
            for r in (parent_grant.get("delegation_allowed_resources", ()) or ())
        }
        targets = parent_grant.get("delegation_allowed_targets", ())
        view["targets"] = set(targets) if targets else set()
        view["ceilings"] = {
            "max_risk_level": str(
                parent_grant.get("delegation_max_risk_level", "") or ""
            ),
            "max_timeout_seconds": parent_grant.get(
                "delegation_max_timeout_seconds", 0
            ),
            "require_verification": parent_grant.get(
                "delegation_require_verification", None
            ),
            "max_side_effect": str(
                parent_grant.get("delegation_max_side_effect", "") or ""
            ),
        }
        view["expiry"] = str(parent_grant.get("delegation_expires_at", "") or "")
    except (TypeError, ValueError, AttributeError):
        return {
            "capabilities": set(),
            "resources": set(),
            "targets": set(),
            "ceilings": None,
            "expiry": None,
        }
    return view


def prove_edge(
    child_grant: Mapping[str, Any],
    child_view: Mapping[str, Any],
    parent_view: Mapping[str, Any],
) -> Tuple[bool, str]:
    """Prove child_grant ⊆ parent_view for one derivation edge.

    child_view: {"capability": str|None, "grid": str, "generation": int,
                 "target": str, "resource_id": str}.
    parent_view: as resolved by resolve_parent_view().
    Root edges (parent_view["ceilings"] is None) additionally require
    explicit ceilings on the child grant.
    """
    try:
        caps = set(child_grant.get("delegation_allowed_capabilities", ()) or ())
        if not caps or not caps <= set(parent_view.get("capabilities", set())):
            return False, "capability-escalation"
        child_resources = {
            _triple(r)
            for r in (child_grant.get("delegation_allowed_resources", ()) or ())
        }
        parent_resources = set(parent_view.get("resources", set()))
        if child_resources and not child_resources <= parent_resources:
            return False, "resource-escalation"
        child_targets = set(child_grant.get("delegation_allowed_targets", ()) or ())
        if child_targets and not target_subset(
            child_targets, parent_view.get("targets")
        ):
            return False, "target-escalation"
        ceilings = parent_view.get("ceilings")
        try:
            eff = {
                "max_risk_level": str(
                    child_grant.get("delegation_max_risk_level", "") or ""
                ),
                "max_timeout_seconds": child_grant.get(
                    "delegation_max_timeout_seconds", 0
                ),
                "require_verification": child_grant.get(
                    "delegation_require_verification", None
                ),
                "max_side_effect": str(
                    child_grant.get("delegation_max_side_effect", "") or ""
                ),
            }
        except (TypeError, ValueError, AttributeError):
            return False, "malformed-ceilings"
        if ceilings is None:
            # Root edge: ceilings must be explicit (nothing to inherit).
            if (
                not eff["max_risk_level"]
                or eff["max_risk_level"] not in RISK_SEVERITY
                or not isinstance(eff["max_timeout_seconds"], (int, float))
                or isinstance(eff["max_timeout_seconds"], bool)
                or eff["max_timeout_seconds"] <= 0
                or not isinstance(eff["require_verification"], bool)
                or not eff["max_side_effect"]
                or eff["max_side_effect"] not in SIDE_EFFECT_SEVERITY
            ):
                return False, "root-ceilings-must-be-explicit"
        else:
            # Nested edge: inherit-or-narrow per dimension.
            child_risk = eff["max_risk_level"] or ceilings.get("max_risk_level", "")
            if not risk_allows(child_risk, ceilings.get("max_risk_level", "")):
                return False, "constraint-weakening:risk"
            child_timeout = eff["max_timeout_seconds"]
            if not child_timeout or child_timeout <= 0:
                child_timeout = ceilings.get("max_timeout_seconds", 0)
            if not timeout_allows(child_timeout, ceilings.get("max_timeout_seconds", 0)):
                return False, "constraint-weakening:timeout"
            child_ver = eff["require_verification"]
            if child_ver is None:
                child_ver = ceilings.get("require_verification", None)
            if not verification_allows(child_ver, ceilings.get("require_verification", None)):
                return False, "constraint-weakening:verification"
            child_se = eff["max_side_effect"] or ceilings.get("max_side_effect", "")
            if not side_effect_allows(child_se, ceilings.get("max_side_effect", "")):
                return False, "constraint-weakening:side-effect"
        if not lifetime_subset(
            str(child_grant.get("delegation_expires_at", "") or ""),
            str(parent_view.get("expiry", "") or ""),
        ):
            return False, "lifetime-extension"
        # The child binding itself must sit inside the granted scope.
        # An unidentifiable capability can never prove membership.
        if caps:
            child_cap = child_view.get("capability")
            if not child_cap or str(child_cap) not in caps:
                return False, "child-binding-outside-grant:capability"
        triple = (
            str(child_view.get("resource_id", "") or ""),
            str(child_view.get("grid", "") or ""),
            child_view.get("generation", 0),
        )
        try:
            triple = (triple[0], triple[1], int(triple[2] or 0))
        except (TypeError, ValueError):
            return False, "malformed-child-binding"
        if child_resources and triple not in child_resources:
            return False, "child-binding-outside-grant:resource"
        # Target membership: with a non-empty allowlist the action must
        # present an exact listed target. An absent target can never
        # prove membership (fail closed).
        child_targets = set(child_grant.get("allowed_targets", ()) or ())
        if child_targets:
            action_target = str(child_view.get("target", "") or "")
            if not action_target or action_target not in child_targets:
                return False, "child-binding-outside-grant:target"
        return True, ""
    except (TypeError, ValueError, AttributeError) as exc:
        return False, f"malformed-edge:{exc}"


# ---------------------------------------------------------------------------
# Durable grant views + chain walk + dispatch verification
# ---------------------------------------------------------------------------

#: Durable delegation fields (flat, mirroring DurableActionState). A
#: grant mapping uses exactly these keys — one vocabulary from the
#: record through the authority to enforcement, no translation layer.
GRANT_FIELDS = (
    "delegation_id",
    "delegation_parent_mission_id",
    "delegation_parent_action_id",
    "delegation_parent_delegation_id",
    "delegation_root_mission_id",
    "delegation_root_action_id",
    "delegation_root_governed_registration_id",
    "delegation_root_generation",
    "delegation_delegator_grid",
    "delegation_delegator_agent_id",
    "delegation_delegate_agent_id",
    "delegation_delegate_grid",
    "delegation_allowed_capabilities",
    "delegation_allowed_resources",
    "delegation_allowed_targets",
    "delegation_max_risk_level",
    "delegation_max_timeout_seconds",
    "delegation_require_verification",
    "delegation_max_side_effect",
    "delegation_created_at",
    "delegation_expires_at",
    "delegation_state",
    "delegation_revoked_at",
    "delegation_revoke_reason",
)


def grant_view(action: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """Grant mapping for one durable action, or None when un-delegated."""
    if not isinstance(action, dict):
        return None
    if not (action.get("delegation_id") or ""):
        return None
    return {key: action.get(key) for key in GRANT_FIELDS}

def _grant_state_of(grant: Mapping[str, Any]) -> str:
    state = grant.get("delegation_state", "")
    if hasattr(state, "value"):
        state = state.value
    return str(state or "")


def walk_chain(
    action_states: Mapping[str, Any],
    leaf_action_id: str,
    now_iso: str,
) -> Tuple[bool, str, List[Tuple[str, Mapping[str, Any], Mapping[str, Any]]]]:
    """Walk parent_delegation_id links from the leaf to the root.

    Returns (ok, reason, chain) where chain is [(action_id, action_dict,
    grant_dict)] from leaf outward. Enforces: resolvable parents,
    depth bound, acyclicity, ACTIVE state, unexpired grants, root
    consistency (every grant's root_* pins the terminal root).
    Pure durable proof — no RRM, no clock reads (now_iso passed in).
    """
    chain: List[Tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    seen = set()
    current_action_id = leaf_action_id
    depth = 0
    while True:
        action = action_states.get(current_action_id)
        if not isinstance(action, dict):
            return False, "unknown-parent-action", []
        grant = grant_view(action)
        if grant is None or not grant.get("delegation_id"):
            return False, "unknown-parent-grant", []
        gid = str(grant.get("delegation_id"))
        if gid in seen:
            return False, "delegation-cycle", []
        seen.add(gid)
        depth += 1
        if depth > MAX_DELEGATION_DEPTH:
            return False, "nesting-depth-overflow", []
        if _grant_state_of(grant) != DelegationState.ACTIVE.value:
            return False, "ancestor-not-active", []
        if is_expired(str(grant.get("delegation_expires_at", "") or ""), now_iso):
            return False, "ancestor-expired", []
        chain.append((current_action_id, action, grant))
        parent_delegation = str(
            grant.get("delegation_parent_delegation_id", "") or ""
        )
        if not parent_delegation:
            break
        # Resolve the parent grant: find the action carrying it.
        parent_action_id = None
        for aid, adict in action_states.items():
            if not isinstance(adict, dict):
                continue
            pg = grant_view(adict)
            if pg is not None and str(pg.get("delegation_id", "")) == parent_delegation:
                parent_action_id = aid
                break
        if parent_action_id is None:
            return False, "unknown-parent-grant", []
        current_action_id = parent_action_id
    # Root consistency: every grant's root_* must pin the terminal root.
    leaf_grant = chain[0][2]
    root_mission = str(leaf_grant.get("delegation_root_mission_id", "") or "")
    root_action = str(leaf_grant.get("delegation_root_action_id", "") or "")
    root_grid = str(
        leaf_grant.get("delegation_root_governed_registration_id", "") or ""
    )
    try:
        root_gen = int(leaf_grant.get("delegation_root_generation", 0) or 0)
    except (TypeError, ValueError):
        return False, "malformed-root-generation", []
    if not root_mission or not root_action:
        return False, "malformed-root-reference", []
    for _aid, _action, grant in chain:
        if (
            str(grant.get("delegation_root_mission_id", "") or "") != root_mission
            or str(grant.get("delegation_root_action_id", "") or "") != root_action
            or str(grant.get("delegation_root_governed_registration_id", "") or "")
            != root_grid
        ):
            return False, "root-ceiling-divergence", []
        try:
            if int(grant.get("delegation_root_generation", 0) or 0) != root_gen:
                return False, "root-ceiling-divergence", []
        except (TypeError, ValueError):
            return False, "malformed-root-generation", []
    return True, "", chain


def _plan_capability(data: Mapping[str, Any], action_id: str) -> str:
    try:
        for entry in data.get("plan", []) or ():
            if isinstance(entry, dict) and entry.get("action_id") == action_id:
                return str(entry.get("capability", "") or "")
    except (TypeError, AttributeError):
        pass
    return ""


def verify_grant_dispatch(
    data: Mapping[str, Any],
    action_id: str,
    *,
    presenter_executor_id: Optional[str] = None,
    now_iso: str = "",
) -> Tuple[bool, str, List[Tuple[str, Mapping[str, Any], Mapping[str, Any]]]]:
    """Full pure delegation proof for one productive handoff.

    ``data`` is the FULL mission mapping (with ``action_states`` and
    ``plan``) — never the bare action-states sub-mapping; passing the
    sub-mapping fails closed with unknown-action by construction.
    Verifies: a grant exists; presenter matches the delegate (when a
    presenter is given); the chain walks to a consistent root within
    depth bounds with every grant ACTIVE and unexpired; every edge
    re-proves child ⊆ parent (creation proof recomputed from durable
    state, so post-creation tampering fails closed).
    Actions without a grant pass through as (True, "not-delegated", []).
    """
    try:
        action_states = data.get("action_states", {}) or {}
        action = action_states.get(action_id)
        if not isinstance(action, dict):
            return False, "unknown-action", []
        grant = grant_view(action)
        if grant is None:
            return True, "not-delegated", []
        if not str(grant.get("delegation_id", "") or ""):
            return False, "malformed-grant", []
        if presenter_executor_id is not None:
            if str(presenter_executor_id or "") != str(
                grant.get("delegation_delegate_agent_id", "") or ""
            ):
                return False, "presenter-not-delegate", []
        ok, reason, chain = walk_chain(action_states, action_id, now_iso)
        if not ok:
            return False, reason, []
        # Re-prove every edge from durable state.
        for index, (aid, adict, gdict) in enumerate(chain):
            parent_view = _edge_parent_view(data, action_states, gdict)
            if parent_view is None:
                return False, "unknown-parent-action", []
            child_view = _action_view(data, aid, adict)
            proved, why = prove_edge(gdict, child_view, parent_view)
            if not proved:
                return False, why, []
            _ = index
        return True, "", chain
    except (TypeError, ValueError, AttributeError) as exc:
        return False, f"malformed-delegation:{exc}", []


def _edge_parent_view(
    data: Mapping[str, Any],
    action_states: Mapping[str, Any],
    grant: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    """Resolve the effective parent view for one edge of a walked chain."""
    parent_action_id = str(grant.get("delegation_parent_action_id", "") or "")
    parent_action = action_states.get(parent_action_id)
    if not isinstance(parent_action, dict):
        return None
    parent_delegation_id = str(
        grant.get("delegation_parent_delegation_id", "") or ""
    )
    parent_grant: Optional[Mapping[str, Any]] = None
    if parent_delegation_id:
        for _aid, adict in action_states.items():
            if not isinstance(adict, dict):
                continue
            pg = grant_view(adict)
            if pg is not None and str(pg.get("delegation_id", "")) == parent_delegation_id:
                parent_grant = pg
                break
        if parent_grant is None:
            return None
    return resolve_parent_view(
        parent_action,
        _plan_capability(data, parent_action_id),
        parent_grant,
    )


def _action_view(
    data: Mapping[str, Any], action_id: str, action: Mapping[str, Any]
) -> Dict[str, Any]:
    """The child binding view for one edge proof."""
    try:
        gen = int(action.get("expected_resource_generation", 0) or 0)
    except (TypeError, ValueError):
        gen = 0
    return {
        "capability": _plan_capability(data, action_id) or None,
        "resource_id": str(action.get("expected_resource_id", "") or ""),
        "grid": str(action.get("expected_governed_registration_id", "") or ""),
        "generation": gen,
        "target": str(action.get("expected_resource_id", "") or ""),
    }


def _level_str(value: Any) -> str:
    """Normalize an enum-or-string level for severity comparison.

    Contract fields may arrive as enums (SideEffectLevel) or plain
    strings; str() on an enum yields "SideEffectLevel.NONE", never the
    severity key — so unwrap .value first (G9 lesson).
    """
    return str(getattr(value, "value", value) or "")


def contract_within_grant(
    contract_values: Mapping[str, Any], effective: Mapping[str, Any]
) -> Tuple[bool, str]:
    """Check a live runtime contract against effective grant ceilings.

    contract_values: {"risk_level": str|enum, "timeout": number,
                      "verification_required": bool,
                      "side_effect": str|enum}.
    effective: resolved ceilings (inheritance already applied).
    """
    try:
        if not risk_allows(
            _level_str(contract_values.get("risk_level", "")),
            _level_str(effective.get("max_risk_level", "")),
        ):
            return False, "contract-risk-exceeds-ceiling"
        timeout = contract_values.get("timeout", 0)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
            return False, "malformed-contract-timeout"
        ceiling = effective.get("max_timeout_seconds", 0)
        if not timeout_allows(timeout, ceiling):
            return False, "contract-timeout-exceeds-ceiling"
        if not verification_allows(
            contract_values.get("verification_required", None),
            effective.get("require_verification", None),
        ):
            return False, "contract-verification-weakened"
        if not side_effect_allows(
            _level_str(contract_values.get("side_effect", "")),
            _level_str(effective.get("max_side_effect", "") or ""),
        ):
            return False, "contract-side-effect-exceeds-ceiling"
        return True, ""
    except (TypeError, ValueError, AttributeError) as exc:
        return False, f"malformed-contract:{exc}"


def resolve_effective_ceilings(
    chain: List[Tuple[str, Mapping[str, Any], Mapping[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Resolve inheritance along a walked chain (leaf outward).

    Nearest explicit value wins per dimension; a dimension explicit
    nowhere resolves to the root edge requirement (must have been
    explicit at creation — enforced there, rechecked here).
    """
    effective: Dict[str, Any] = {
        "max_risk_level": "",
        "max_timeout_seconds": 0,
        "require_verification": None,
        "max_side_effect": "",
    }
    for _aid, _action, grant in chain:
        if not effective["max_risk_level"] and grant.get("delegation_max_risk_level"):
            effective["max_risk_level"] = str(grant["delegation_max_risk_level"])
        if not effective["max_timeout_seconds"] and grant.get(
            "delegation_max_timeout_seconds"
        ):
            try:
                value = grant["delegation_max_timeout_seconds"]
                if isinstance(value, bool):
                    raise ValueError("bool timeout")
                effective["max_timeout_seconds"] = float(value)
            except (TypeError, ValueError):
                return None
        if effective["require_verification"] is None and isinstance(
            grant.get("delegation_require_verification"), bool
        ):
            effective["require_verification"] = grant[
                "delegation_require_verification"
            ]
        if not effective["max_side_effect"] and grant.get("delegation_max_side_effect"):
            effective["max_side_effect"] = str(grant["delegation_max_side_effect"])
    return effective


def confirmation_basis_for_grant(
    delegation_id: str,
    delegate_agent_id: str,
    capability: str,
    governed_registration_id: str,
    generation: Any,
    target: str,
    expires_at: str,
) -> str:
    """Canonical delegation-bound confirmation basis digest.

    Binds delegated semantics into the confirmation requirement so a
    confirmation issued for a different delegate, delegation, target,
    resource, capability, or lifetime can never authorize this action:
    the digest comparison at validation time fails closed.
    """
    try:
        gen = int(generation or 0)
    except (TypeError, ValueError):
        gen = 0
    return hashlib.sha256(
        json.dumps(
            [
                str(delegation_id or ""),
                str(delegate_agent_id or ""),
                str(capability or ""),
                str(governed_registration_id or ""),
                gen,
                str(target or ""),
                str(expires_at or ""),
            ],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def mint_delegation_id(nonce: str = "") -> str:
    """Mint a delegation identity. The authority mints; callers never supply."""
    from uuid import uuid4

    del nonce  # reserved for future domain separation; uniqueness from uuid4
    return f"dlg_{uuid4().hex[:16]}"


__all__ = [
    "MAX_DELEGATION_DEPTH",
    "RISK_SEVERITY",
    "SIDE_EFFECT_SEVERITY",
    "DelegationError",
    "DelegationState",
    "DelegatedResource",
    "DelegationGrant",
    "is_expired",
    "capability_subset",
    "resource_subset",
    "target_subset",
    "lifetime_subset",
    "risk_allows",
    "timeout_allows",
    "verification_allows",
    "side_effect_allows",
    "resolve_parent_view",
    "prove_edge",
    "walk_chain",
    "verify_grant_dispatch",
    "resolve_effective_ceilings",
    "contract_within_grant",
    "confirmation_basis_for_grant",
    "mint_delegation_id",
]
