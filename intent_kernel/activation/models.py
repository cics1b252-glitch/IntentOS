"""Movement 18 — Typed Activation Contracts.

DISCOVERY IS EVIDENCE.
PROPOSAL MAY REQUEST REGISTRATION.
APPROVAL MAY AUTHORIZE PROMOTION.
REGISTRATION PROVES THE RESOURCE IS KNOWN.
ACTIVATION PROVES THE RESOURCE SATISFIES GOVERNED PREREQUISITES.

DISCOVERY != PROPOSAL
PROPOSAL != APPROVAL
APPROVAL != REGISTRATION
REGISTRATION != ACTIVATION
ACTIVATION != AVAILABILITY
AVAILABILITY != ELIGIBILITY
ELIGIBILITY != AUTHORIZATION
AUTHORIZATION != EXECUTION
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from intent_kernel.discovery.models import ResourceDiscoveryKind
from intent_kernel.time_utils import utc_iso


# ---------------------------------------------------------------------------
# Activation status lifecycle
# ---------------------------------------------------------------------------


class ResourceActivationStatus(str, Enum):
    """Lifecycle states for an activation request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CONSUMED = "consumed"


class ResourceActivationDecisionType(str, Enum):
    """Typed decision kinds — no free-text ambiguity."""

    APPROVE = "approve"
    REJECT = "reject"


# ---------------------------------------------------------------------------
# Authority-bearing field rejection list
# ---------------------------------------------------------------------------

_ACTIVATION_AUTHORITY_FIELDS: frozenset[str] = frozenset({
    "authorized",
    "execute",
    "verified",
    "completed",
    "trusted",
    "admin",
    "bypass",
    "override",
    "eligible",
})


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResourceActivationRequest:
    """A typed, immutable request to evaluate activation prerequisites.

    ACTIVATION_REQUEST_ONLY — must NOT mutate RRM, grant authority,
    or manufacture eligibility.
    """

    request_id: str
    resource_id: str
    resource_kind: ResourceDiscoveryKind
    discovery_id: str
    registration_id: str
    created_at: str = field(default_factory=utc_iso)
    status: ResourceActivationStatus = ResourceActivationStatus.PENDING
    scope: str = "global"
    metadata: dict[str, object] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "resource_id": self.resource_id,
            "resource_kind": self.resource_kind.value,
            "discovery_id": self.discovery_id,
            "registration_id": self.registration_id,
            "created_at": self.created_at,
            "status": self.status.value,
            "scope": self.scope,
        }


@dataclass(frozen=True, slots=True)
class ResourceActivationDecision:
    """A typed decision on an activation request.

    ACTIVATION_ONLY — exact-request-bound, exact-resource-bound,
    non-transferable, single-use, auditable.
    """

    decision_id: str
    request_id: str
    resource_id: str
    resource_kind: ResourceDiscoveryKind
    decision_type: ResourceActivationDecisionType
    decided_at: str = field(default_factory=utc_iso)
    reasoning: str = ""
    prerequisites_evaluated: tuple[str, ...] = ()
    scope: str = ""
    metadata: dict[str, object] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "request_id": self.request_id,
            "resource_id": self.resource_id,
            "resource_kind": self.resource_kind.value,
            "decision_type": self.decision_type.value,
            "decided_at": self.decided_at,
            "reasoning": self.reasoning,
            "prerequisites_evaluated": list(self.prerequisites_evaluated),
            "scope": self.scope,
        }


@dataclass(frozen=True, slots=True)
class ResourceActivationResult:
    """Immutable audit record of an activation application attempt."""

    success: bool
    request_id: str
    decision_id: str
    resource_id: str
    applied_at: str = field(default_factory=utc_iso)
    reason: str = ""
    fields_updated: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "request_id": self.request_id,
            "decision_id": self.decision_id,
            "resource_id": self.resource_id,
            "applied_at": self.applied_at,
            "reason": self.reason,
            "fields_updated": list(self.fields_updated),
        }
