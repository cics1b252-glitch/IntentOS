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

from dataclasses import dataclass, field
from enum import Enum

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


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResourcePromotionProposal:
    """A typed, immutable proposal to register a discovered resource.

    PROPOSAL_ONLY — must NOT register anything, mutate RRM, or grant authority.
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

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "proposal_id": self.proposal_id,
            "evidence_identity": self.evidence_identity,
            "decision_type": self.decision_type.value,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "reasoning": self.reasoning,
            "scope": self.scope,
        }


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
        }
