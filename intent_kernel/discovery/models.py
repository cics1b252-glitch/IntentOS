"""Canonical Resource Discovery models — Movement 16.

All models are read-only.  Status and kind enumerations use distinct values from
RRM lifecycle statuses to prevent accidental authority leakage through
cross-domain reuse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from intent_kernel.time_utils import utc_iso


class ResourceDiscoveryStatus(str, Enum):
    """Discovery-specific states — NOT RRM runtime lifecycle statuses."""

    OBSERVED = "OBSERVED"
    STALE = "STALE"
    REVOKED = "REVOKED"
    UNAVAILABLE_AT_SOURCE = "UNAVAILABLE_AT_SOURCE"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


class ResourceDiscoveryKind(str, Enum):
    """Observed resource category."""

    PROVIDER = "PROVIDER"
    TOOL = "TOOL"
    CAPABILITY = "CAPABILITY"
    ENVIRONMENT = "ENVIRONMENT"
    AGENT = "AGENT"
    LOCAL_PROGRAM = "LOCAL_PROGRAM"
    MCP_RESOURCE = "MCP_RESOURCE"
    CONNECTED_SERVICE = "CONNECTED_SERVICE"
    DEVICE = "DEVICE"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True, slots=True)
class ResourceDiscoveryEvidence:
    """Typed, immutable evidence record of a single observed resource."""

    discovery_id: str
    resource_kind: ResourceDiscoveryKind
    resource_id: str
    display_name: str
    capability_claims: tuple[str, ...] = ()
    source: str = ""
    source_type: str = ""
    observed_at: str = field(default_factory=utc_iso)
    observed_by: str = ""
    status: ResourceDiscoveryStatus = ResourceDiscoveryStatus.OBSERVED
    confidence: float = 0.0
    health_observed: str = "unknown"
    health_source: str = ""
    credential_required: bool = False
    credential_available: bool = False
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "discovery_id": self.discovery_id,
            "resource_kind": self.resource_kind.value,
            "resource_id": self.resource_id,
            "display_name": self.display_name,
            "capability_claims": list(self.capability_claims),
            "source": self.source,
            "source_type": self.source_type,
            "observed_at": self.observed_at,
            "observed_by": self.observed_by,
            "status": self.status.value,
            "confidence": self.confidence,
            "health_observed": self.health_observed,
            "health_source": self.health_source,
            "credential_required": self.credential_required,
            "credential_available": self.credential_available,
        }


@dataclass(frozen=True, slots=True)
class ResourceDiscoveryCorrelation:
    """Derived read-only cross-reference between a discovery and RRM truth."""

    discovery_id: str
    resource_id: str
    resource_kind: ResourceDiscoveryKind
    rrm_registered: bool = False
    rrm_available: bool = False
    rrm_eligible: bool = False
    correlation_status: str = "no_match"


@dataclass(frozen=True, slots=True)
class ResourceDiscoverySnapshot:
    """Deterministic, read-only snapshot of all current discovery evidence."""

    discoveries: tuple[ResourceDiscoveryEvidence, ...] = ()
    generated_at: str = field(default_factory=utc_iso)
    discovery_count: int = 0
    rrm_cross_reference: tuple[ResourceDiscoveryCorrelation, ...] = ()
