"""Resource Registration Proposal — PROPOSAL_ONLY (Movement 16).

A proposal describes what COULD be registered in the future.
It must NOT register anything.
It must NOT mutate RRM.
It must NOT grant any authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from intent_kernel.discovery.models import ResourceDiscoveryKind
from intent_kernel.time_utils import utc_iso


@dataclass(frozen=True, slots=True)
class ResourceRegistrationProposal:
    """Non-productive typed proposal for future resource registration."""

    discovery_id: str
    resource_kind: ResourceDiscoveryKind
    resource_id: str
    proposed_registration_type: str = ""
    proposed_capabilities: tuple[str, ...] = ()
    reasoning: str = ""
    created_at: str = field(default_factory=utc_iso)
    status: str = "proposed"

    def accept(self) -> ResourceRegistrationProposal:
        """Return a new proposal marked accepted — does NOT register."""
        return ResourceRegistrationProposal(
            discovery_id=self.discovery_id,
            resource_kind=self.resource_kind,
            resource_id=self.resource_id,
            proposed_registration_type=self.proposed_registration_type,
            proposed_capabilities=self.proposed_capabilities,
            reasoning=self.reasoning,
            created_at=self.created_at,
            status="accepted",
        )

    def reject(self) -> ResourceRegistrationProposal:
        """Return a new proposal marked rejected."""
        return ResourceRegistrationProposal(
            discovery_id=self.discovery_id,
            resource_kind=self.resource_kind,
            resource_id=self.resource_id,
            proposed_registration_type=self.proposed_registration_type,
            proposed_capabilities=self.proposed_capabilities,
            reasoning=self.reasoning,
            created_at=self.created_at,
            status="rejected",
        )
