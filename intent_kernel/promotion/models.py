"""Movement 17 — Typed Promotion Contracts.

EVIDENCE MAY SUPPORT A PROPOSAL.
A PROPOSAL MAY REQUEST REGISTRATION.
A DECISION MAY AUTHORIZE PROMOTION.
ONLY THE CANONICAL REGISTRATION BOUNDARY MAY MUTATE CANONICAL RESOURCE STATE.

DISCOVERY != PROPOSAL
PROPOSAL != APPROVAL
APPROVAL != REGISTRATION
REGISTRATION != AVAILABILITY
AVAILABILITY != ELIGIBILITY
ELIGIBILITY != AUTHORIZATION
AUTHORIZATION != EXECUTION
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from intent_kernel.discovery.models import ResourceDiscoveryKind
from intent_kernel.time_utils import utc_iso


# ---------------------------------------------------------------------------
# Promotion status lifecycle
# ---------------------------------------------------------------------------


class ResourcePromotionStatus(str, Enum):
    """Lifecycle states for a promotion proposal."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CONSUMED = "consumed"


class ResourcePromotionDecisionType(str, Enum):
    """Typed decision kinds — no free-text ambiguity."""

    APPROVE = "approve"
    REJECT = "reject"


# ---------------------------------------------------------------------------
# Authority-bearing field rejection list
# ---------------------------------------------------------------------------

_PROHIBITED_PROPOSAL_FIELDS: frozenset[str] = frozenset({
    "authorized",
    "eligible",
    "execute",
    "verified",
    "trusted",
    "admin",
    "permission",
    "granted",
    "bypass",
    "override",
})


def _detach_promotion_value(value: Any) -> Any:
    """Recursively clone caller-owned data into fully disconnected structures.

    B-2C aliasing repair: guarantees the canonical proposal descriptor and
    metadata share NO mutable container/leaf with the caller input graph at any
    nesting depth. Only the value types actually admitted by plain-container
    contracts are copied; any other (arbitrary/custom) object is rejected
    FAIL-CLOSED so that no caller-defined executable protocol hook
    (e.g. ``__deepcopy__`` / ``__reduce__``) runs and no caller-owned mutable
    reference can be smuggled into canonical proposal state.

    Immutable / effectively-immutable values (str/int/float/bool/bytes, Enum,
    datetime, uuid) are returned as-is — they cannot alias mutable state.
    """
    if value is None or isinstance(value, (str, int, float, bool, bytes, Enum)):
        return value
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, dict):
        return {k: _detach_promotion_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_detach_promotion_value(v) for v in value)
    if isinstance(value, set):
        return set(_detach_promotion_value(v) for v in value)
    if isinstance(value, frozenset):
        return frozenset(_detach_promotion_value(v) for v in value)
    raise ValueError(
        "promotion value refuses unsupported type: "
        f"{type(value).__name__} (must be a plain container or scalar)"
    )


@dataclass(frozen=True, slots=True)
class ReRegistrationPrecondition:
    """Movement 31.2B-2C — immutable governed re-registration precondition.

    Carried immutably on an approved ResourcePromotionDecision when the decision
    authorizes re-registration of an EXACT retired predecessor. DATA ONLY — no
    authority, no candidate identity, no successor identity.

    Exact semantic fields correspond to the canonical
    ``ResourceTombstone(resource_kind, resource_id,
    governed_registration_id, observed_generation)`` used for authorization.

    No defaults convert a missing generation into 0 or 1: a construction without
    an explicit valid generation FAILS CLOSED.
    """

    resource_kind: "ResourceType"
    resource_id: str
    retired_governed_registration_id: str
    retired_observed_generation: int

    def __post_init__(self) -> None:
        from intent_kernel.rrm.models import ResourceType
        if not isinstance(self.resource_kind, ResourceType):
            raise ValueError(
                "resource_kind must be a canonical ResourceType, "
                f"got {type(self.resource_kind).__name__}"
            )
        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise ValueError("resource_id must be a non-empty string")
        if (
            not isinstance(self.retired_governed_registration_id, str)
            or not self.retired_governed_registration_id.strip()
        ):
            raise ValueError(
                "retired_governed_registration_id must be a non-empty string"
            )
        if (
            not isinstance(self.retired_observed_generation, int)
            or isinstance(self.retired_observed_generation, bool)
            or self.retired_observed_generation < 1
        ):
            raise ValueError(
                "retired_observed_generation must be a positive int (>=1), "
                "never a missing/legacy 0 or 1 default"
            )


@dataclass(frozen=True, slots=True)
class FirstGovernancePrecondition:
    """M31.3B-1B — immutable bootstrap first-governance precondition.

    Carried immutably on an approved ResourcePromotionDecision when the decision
    authorizes first governance of an EXISTING pre-governed canonical resource.
    DATA ONLY — no authority, no governed registration lineage, no candidate
    identity.

    Exact semantic fields correspond to the canonical
    ``FirstGovernanceRequest(resource_kind, resource_id,
    expected_pre_governed_generation, expected_ungoverned_lineage)`` used for
    authorization.

    No defaults convert a missing generation into 0 or 1: a construction without
    an explicit valid pre-governed generation FAILS CLOSED.
    """

    resource_kind: "ResourceType"
    resource_id: str
    expected_pre_governed_generation: int
    expected_ungoverned_lineage: bool = True

    def __post_init__(self) -> None:
        from intent_kernel.rrm.models import ResourceType
        if not isinstance(self.resource_kind, ResourceType):
            raise ValueError(
                "resource_kind must be a canonical ResourceType, "
                f"got {type(self.resource_kind).__name__}"
            )
        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise ValueError("resource_id must be a non-empty string")
        if (
            not isinstance(self.expected_pre_governed_generation, int)
            or isinstance(self.expected_pre_governed_generation, bool)
            or self.expected_pre_governed_generation < 1
        ):
            raise ValueError(
                "expected_pre_governed_generation must be a positive int (>=1), "
                "never a missing/legacy 0 or 1 default"
            )
        if not self.expected_ungoverned_lineage:
            raise ValueError(
                "first governance requires expected_ungoverned_lineage=True"
            )


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResourcePromotionProposal:
    """A typed, immutable proposal to register a discovered resource.

    PROPOSAL_ONLY — must NOT register anything, mutate RRM, or grant authority.

    B-2C aliasing repair: ``proposed_descriptor`` and ``metadata`` are
    recursively detached from the caller-owned input graphs at construction, so
    mutating the original caller structure afterwards cannot alter canonical
    proposal state at any nesting depth.
    """

    proposal_id: str
    discovery_id: str
    resource_id: str
    resource_kind: ResourceDiscoveryKind
    discovery_source: str
    evidence_identity: str
    proposed_descriptor: dict[str, object] = field(default_factory=dict)
    requested_scope: str = "global"
    created_at: str = field(default_factory=utc_iso)
    status: ResourcePromotionStatus = ResourcePromotionStatus.PENDING
    reasoning: str = ""
    metadata: dict[str, object] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "proposed_descriptor",
            _detach_promotion_value(self.proposed_descriptor),
        )
        object.__setattr__(
            self, "metadata", _detach_promotion_value(self.metadata),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "discovery_id": self.discovery_id,
            "resource_id": self.resource_id,
            "resource_kind": self.resource_kind.value,
            "discovery_source": self.discovery_source,
            "evidence_identity": self.evidence_identity,
            "proposed_descriptor": dict(self.proposed_descriptor),
            "requested_scope": self.requested_scope,
            "created_at": self.created_at,
            "status": self.status.value,
            "reasoning": self.reasoning,
        }


@dataclass(frozen=True, slots=True)
class ResourcePromotionDecision:
    """A typed decision on a promotion proposal.

    APPROVAL_ONLY — exact-proposal-bound, exact-evidence-bound,
    non-transferable, single-use, auditable.
    """

    decision_id: str
    proposal_id: str
    evidence_identity: str
    decision_type: ResourcePromotionDecisionType
    decided_at: str = field(default_factory=utc_iso)
    decided_by: str = ""
    reasoning: str = ""
    scope: str = ""
    metadata: dict[str, object] = field(default_factory=dict, compare=False)
    re_registration_precondition: Optional["ReRegistrationPrecondition"] = None
    first_governance_precondition: Optional["FirstGovernancePrecondition"] = None

    def __post_init__(self) -> None:
        if (
            self.re_registration_precondition is not None
            and not isinstance(self.re_registration_precondition, ReRegistrationPrecondition)
        ):
            raise ValueError(
                "re_registration_precondition must be a ReRegistrationPrecondition "
                "or None"
            )
        if (
            self.first_governance_precondition is not None
            and not isinstance(
                self.first_governance_precondition, FirstGovernancePrecondition
            )
        ):
            raise ValueError(
                "first_governance_precondition must be a "
                "FirstGovernancePrecondition or None"
            )
        if (
            self.re_registration_precondition is not None
            and self.first_governance_precondition is not None
        ):
            raise ValueError(
                "a decision may carry re_registration or first_governance, not both"
            )
        object.__setattr__(
            self, "metadata", _detach_promotion_value(self.metadata),
        )

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "decision_id": self.decision_id,
            "proposal_id": self.proposal_id,
            "evidence_identity": self.evidence_identity,
            "decision_type": self.decision_type.value,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "reasoning": self.reasoning,
            "scope": self.scope,
        }
        if self.re_registration_precondition is not None:
            p = self.re_registration_precondition
            out["re_registration_precondition"] = {
                "resource_kind": p.resource_kind.value,
                "resource_id": p.resource_id,
                "retired_governed_registration_id": (
                    p.retired_governed_registration_id
                ),
                "retired_observed_generation": p.retired_observed_generation,
            }
        if self.first_governance_precondition is not None:
            p = self.first_governance_precondition
            out["first_governance_precondition"] = {
                "resource_kind": p.resource_kind.value,
                "resource_id": p.resource_id,
                "expected_pre_governed_generation": (
                    p.expected_pre_governed_generation
                ),
                "expected_ungoverned_lineage": p.expected_ungoverned_lineage,
            }
        return out


@dataclass(frozen=True, slots=True)
class ResourcePromotionResult:
    """Immutable audit record of a promotion attempt."""

    success: bool
    proposal_id: str
    decision_id: str
    registration_type: str
    resource_id: str
    registered_at: str = field(default_factory=utc_iso)
    reason: str = ""
    governed_registration_id: str = ""
    observed_generation: int = 0
    re_registration: bool = False
    metadata: dict[str, object] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "proposal_id": self.proposal_id,
            "decision_id": self.decision_id,
            "registration_type": self.registration_type,
            "resource_id": self.resource_id,
            "registered_at": self.registered_at,
            "reason": self.reason,
            "governed_registration_id": self.governed_registration_id,
            "observed_generation": self.observed_generation,
            "re_registration": self.re_registration,
        }


@dataclass(frozen=True, slots=True)
class BootstrapResourceDeclaration:
    """M31.3B-1B — immutable first-governance declaration for a built-in resource.

    BOOTSTRAP_DATA_ONLY. Names the EXISTING pre-governed canonical resource
    (kind + id) that the bootstrap policy will govern. Carries NO governance
    authority, NO governed lineage, and NO generation — the observed pre-governed
    generation is derived by the governance pipeline from the detached RRM
    snapshot, never supplied on the declaration.

    ``resource_id`` resolves the exact RRM resource:
      - core_app  → the canonical CAPABILITY resource named by ``capability_name``
      - agent     → the canonical AGENT resource keyed by ``executor_id``
      - provider  → the canonical PROVIDER resource keyed by ``executor_id``
    """

    resource_kind: "ResourceType"
    capability_name: str
    executor_kind: str
    executor_id: str
    executor: object = field(default=None, compare=False)

    def __post_init__(self) -> None:
        from intent_kernel.rrm.models import ResourceType
        if not isinstance(self.resource_kind, ResourceType):
            raise ValueError(
                "resource_kind must be a canonical ResourceType, "
                f"got {type(self.resource_kind).__name__}"
            )
        if self.resource_kind.value not in ("capability", "agent", "provider"):
            raise ValueError(
                "bootstrap governance supports capability/agent/provider only, "
                f"got {self.resource_kind.value}"
            )
        if not isinstance(self.capability_name, str) or not self.capability_name.strip():
            raise ValueError("capability_name must be a non-empty string")
        if self.executor_kind not in ("core_app", "agent", "provider"):
            raise ValueError(
                "executor_kind must be core_app/agent/provider, "
                f"got {self.executor_kind!r}"
            )
        if not isinstance(self.executor_id, str) or not self.executor_id.strip():
            raise ValueError("executor_id must be a non-empty string")

    @property
    def resource_id(self) -> str:
        """Exact canonical RRM resource id for this declaration."""
        if self.executor_kind == "core_app":
            return self.capability_name
        return self.executor_id

    @property
    def discovery_kind(self) -> "ResourceDiscoveryKind":
        """Discovery kind observed for this declaration's canonical resource."""
        from intent_kernel.discovery.models import ResourceDiscoveryKind
        if self.executor_kind == "provider":
            return ResourceDiscoveryKind.PROVIDER
        if self.executor_kind == "agent":
            return ResourceDiscoveryKind.AGENT
        return ResourceDiscoveryKind.CAPABILITY

    @classmethod
    def from_registration(cls, registration: object) -> "BootstrapResourceDeclaration":
        """Declare from a canonical capability-registry registration."""
        from intent_kernel.rrm.models import ResourceType

        executor_kind_val = (
            getattr(getattr(registration, "executor_kind", None), "value", None)
        )
        kind_map = {
            "core_app": ResourceType.CAPABILITY,
            "agent": ResourceType.AGENT,
            "provider": ResourceType.PROVIDER,
        }
        resource_kind = kind_map.get(executor_kind_val)
        if resource_kind is None:
            raise ValueError(
                "unsupported registration executor_kind: "
                f"{executor_kind_val!r}"
            )
        capability = getattr(registration, "capability", None)
        capability_name = (
            getattr(capability, "name", "") if capability is not None else ""
        )
        return cls(
            resource_kind=resource_kind,
            capability_name=capability_name,
            executor_kind=executor_kind_val,
            executor_id=getattr(registration, "executor_id", ""),
            executor=getattr(registration, "executor", None),
        )


@dataclass(frozen=True, slots=True)
class BootstrapGovernanceEntry:
    """M31.3B-1B — immutable per-resource outcome of the bootstrap governance pass."""

    resource_kind: "ResourceType"
    resource_id: str
    capability_name: str
    executor_kind: str
    executor_id: str
    success: bool
    outcome: str = ""
    governed_registration_id: str = ""
    resulting_generation: int = 0
    reason: str = ""
    verified: bool = False


@dataclass(frozen=True, slots=True)
class BootstrapGovernanceReport:
    """M31.3B-1B — immutable aggregate report of the bootstrap governance pass.

    ``success`` is True ONLY when every entry governed successfully AND the
    detached post-governance verification pass confirms each governed lineage.
    """

    success: bool
    entries: tuple[BootstrapGovernanceEntry, ...] = ()
    verified: bool = False
    reason: str = ""

    @property
    def governed_count(self) -> int:
        return sum(1 for e in self.entries if e.success)
