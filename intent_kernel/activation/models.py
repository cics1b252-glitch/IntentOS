"""Movement 18 — Typed Activation Contracts.

ACTIVATION MUST VERIFY PREREQUISITE TRUTH.
ACTIVATION MUST NOT INVENT PREREQUISITE TRUTH.

ACTIVATION APPROVAL IS NOT PREREQUISITE EVIDENCE.

The activation pipeline:
  INDEPENDENT EVIDENCE → AUTHORITY VALIDATES → APPROVED →
  BOUNDARY APPLIES TRANSITION → RRM DERIVES ELIGIBILITY

Evidence is INPUT to activation.
Approval is NOT evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

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
# Activation prerequisite evidence types
# ---------------------------------------------------------------------------


class ActivationEvidenceType(str, Enum):
    """Typed evidence categories — no free-text ambiguity."""

    PROVIDER_CONFIGURATION = "provider_configuration"
    PROVIDER_ACCOUNT = "provider_account"
    CAPABILITY_EXECUTABLE = "capability_executable"
    AGENT_IDENTITY = "agent_identity"
    ENVIRONMENT_DISCOVERY = "environment_discovery"
    ACCOUNT_SECRET = "account_secret"


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
# Activation prerequisite evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResourceActivationEvidence:
    """Immutable prerequisite evidence for activation.

    Evidence is INPUT to activation authority.
    Evidence is NOT produced by activation.
    Evidence must exist BEFORE activation approval.
    Evidence must be validated against canonical sources.

    ACTIVATION APPROVAL IS NOT PREREQUISITE EVIDENCE.
    CALLER ASSERTION != CANONICAL SOURCE OF TRUTH.
    """

    evidence_id: str
    resource_id: str
    resource_kind: ResourceDiscoveryKind
    evidence_type: ActivationEvidenceType
    source: str
    source_identity: str = ""
    observed_at: str = field(default_factory=utc_iso)
    scope: str = "global"
    binding_identity: str = ""
    evidence_payload: dict[str, Any] = field(default_factory=dict, compare=False)
    revoked: bool = False

    def is_valid(self) -> bool:
        """Evidence is valid if not revoked."""
        return not self.revoked

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "resource_id": self.resource_id,
            "resource_kind": self.resource_kind.value,
            "evidence_type": self.evidence_type.value,
            "source": self.source,
            "source_identity": self.source_identity,
            "observed_at": self.observed_at,
            "scope": self.scope,
            "binding_identity": self.binding_identity,
            "revoked": self.revoked,
        }


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
    evidence_ids: tuple[str, ...] = ()
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
            "evidence_ids": list(self.evidence_ids),
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
    evidence_verified: tuple[str, ...] = ()
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
            "evidence_verified": list(self.evidence_verified),
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "request_id": self.request_id,
            "decision_id": self.decision_id,
            "resource_id": self.resource_id,
            "applied_at": self.applied_at,
            "reason": self.reason,
            "fields_updated": list(self.fields_updated),
        }
