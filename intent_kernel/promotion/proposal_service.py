"""Movement 17 — Promotion Proposal Service.

PROPOSAL_ONLY — creates typed proposals from discovery evidence.

It may:
  - inspect discovery evidence;
  - derive a proposed descriptor;
  - preserve provenance;
  - reject stale/revoked/invalid evidence;
  - create a proposal identity;
  - store proposal state.

It may NOT:
  - mutate RRM;
  - mutate executable registries;
  - authorize;
  - invoke;
  - execute;
  - verify;
  - complete Missions;
  - create providers, tools, or agents;
  - grant permissions.
"""

from __future__ import annotations

from uuid import uuid4

from intent_kernel.discovery.models import ResourceDiscoveryStatus
from intent_kernel.discovery.service import CanonicalResourceDiscoveryService
from intent_kernel.promotion.models import (
    ResourcePromotionProposal,
    ResourcePromotionStatus,
    _PROHIBITED_PROPOSAL_FIELDS,
)
from intent_kernel.time_utils import utc_iso


class PromotionError(Exception):
    """Raised when a promotion operation violates governance."""


def _derive_descriptor(evidence: object) -> dict[str, object]:
    """Derive a proposed canonical descriptor from discovery evidence."""
    return {
        "resource_id": getattr(evidence, "resource_id", ""),
        "resource_kind": getattr(evidence.resource_kind, "value", "")
        if hasattr(evidence, "resource_kind")
        else "",
        "display_name": getattr(evidence, "display_name", ""),
        "capability_claims": list(getattr(evidence, "capability_claims", ())),
        "source": getattr(evidence, "source", ""),
        "source_type": getattr(evidence, "source_type", ""),
        "health_observed": getattr(evidence, "health_observed", ""),
        "credential_required": getattr(evidence, "credential_required", False),
        "credential_available": getattr(evidence, "credential_available", False),
    }


def _has_prohibited_fields(metadata: dict[str, object]) -> list[str]:
    """Return list of authority-bearing keys found in metadata."""
    return [k for k in metadata if k in _PROHIBITED_PROPOSAL_FIELDS]


class ResourcePromotionProposalService:
    """Creates promotion proposals from discovery evidence.

    PROPOSAL_ONLY — may NOT mutate RRM, authorize, invoke, execute.
    """

    def __init__(
        self,
        discovery_service: CanonicalResourceDiscoveryService,
    ) -> None:
        self._discovery = discovery_service
        self._proposals: dict[str, ResourcePromotionProposal] = {}

    # ------------------------------------------------------------------
    # READ
    # ------------------------------------------------------------------

    def get_proposal(self, proposal_id: str) -> ResourcePromotionProposal | None:
        return self._proposals.get(proposal_id)

    def list_proposals(
        self,
        status: ResourcePromotionStatus | None = None,
    ) -> tuple[ResourcePromotionProposal, ...]:
        if status is None:
            return tuple(self._proposals.values())
        return tuple(p for p in self._proposals.values() if p.status == status)

    @property
    def count(self) -> int:
        return len(self._proposals)

    # ------------------------------------------------------------------
    # WRITE — proposal storage only, zero RRM / registry mutation
    # ------------------------------------------------------------------

    def create_proposal(
        self,
        discovery_id: str,
        *,
        requested_scope: str = "global",
        reasoning: str = "",
        metadata: dict[str, object] | None = None,
    ) -> ResourcePromotionProposal:
        """Validate discovery evidence and create a typed proposal."""
        meta = dict(metadata) if metadata else {}

        # --- reject authority-bearing metadata keys ---
        prohibited = _has_prohibited_fields(meta)
        if prohibited:
            raise PromotionError(
                f"Authority-bearing metadata keys rejected: {prohibited}"
            )

        # --- evidence must exist ---
        evidence = self._discovery.get(discovery_id)
        if evidence is None:
            raise PromotionError(
                f"Discovery evidence not found: {discovery_id}"
            )

        # --- evidence must be OBSERVED ---
        if evidence.status is not ResourceDiscoveryStatus.OBSERVED:
            raise PromotionError(
                f"Cannot propose for {evidence.status.value} evidence "
                f"(discovery_id={discovery_id})"
            )

        proposal_id = f"prop-{uuid4().hex}"
        descriptor = _derive_descriptor(evidence)

        proposal = ResourcePromotionProposal(
            proposal_id=proposal_id,
            discovery_id=discovery_id,
            resource_id=evidence.resource_id,
            resource_kind=evidence.resource_kind,
            discovery_source=evidence.source,
            evidence_identity=evidence.discovery_id,
            proposed_descriptor=descriptor,
            requested_scope=requested_scope,
            created_at=utc_iso(),
            reasoning=reasoning,
            metadata=meta,
        )

        self._proposals[proposal_id] = proposal
        return proposal

    def revoke_proposal(self, proposal_id: str) -> ResourcePromotionProposal:
        """Revoke a PENDING proposal.  Fails closed on unknown / terminal."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise PromotionError(f"Proposal not found: {proposal_id}")
        if proposal.status is not ResourcePromotionStatus.PENDING:
            raise PromotionError(
                f"Cannot revoke proposal in {proposal.status.value} state"
            )
        updated = ResourcePromotionProposal(
            proposal_id=proposal.proposal_id,
            discovery_id=proposal.discovery_id,
            resource_id=proposal.resource_id,
            resource_kind=proposal.resource_kind,
            discovery_source=proposal.discovery_source,
            evidence_identity=proposal.evidence_identity,
            proposed_descriptor=dict(proposal.proposed_descriptor),
            requested_scope=proposal.requested_scope,
            created_at=proposal.created_at,
            status=ResourcePromotionStatus.REVOKED,
            reasoning=proposal.reasoning,
            metadata=dict(proposal.metadata),
        )
        self._proposals[proposal_id] = updated
        return updated

    def expire_proposal(self, proposal_id: str) -> ResourcePromotionProposal:
        """Expire a PENDING proposal.  Fails closed on unknown / terminal."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise PromotionError(f"Proposal not found: {proposal_id}")
        if proposal.status is not ResourcePromotionStatus.PENDING:
            raise PromotionError(
                f"Cannot expire proposal in {proposal.status.value} state"
            )
        updated = ResourcePromotionProposal(
            proposal_id=proposal.proposal_id,
            discovery_id=proposal.discovery_id,
            resource_id=proposal.resource_id,
            resource_kind=proposal.resource_kind,
            discovery_source=proposal.discovery_source,
            evidence_identity=proposal.evidence_identity,
            proposed_descriptor=dict(proposal.proposed_descriptor),
            requested_scope=proposal.requested_scope,
            created_at=proposal.created_at,
            status=ResourcePromotionStatus.EXPIRED,
            reasoning=proposal.reasoning,
            metadata=dict(proposal.metadata),
        )
        self._proposals[proposal_id] = updated
        return updated

    def transition_to_consumed(
        self,
        proposal_id: str,
    ) -> ResourcePromotionProposal:
        """Internal: transition proposal to CONSUMED after registration."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise PromotionError(f"Proposal not found: {proposal_id}")
        updated = ResourcePromotionProposal(
            proposal_id=proposal.proposal_id,
            discovery_id=proposal.discovery_id,
            resource_id=proposal.resource_id,
            resource_kind=proposal.resource_kind,
            discovery_source=proposal.discovery_source,
            evidence_identity=proposal.evidence_identity,
            proposed_descriptor=dict(proposal.proposed_descriptor),
            requested_scope=proposal.requested_scope,
            created_at=proposal.created_at,
            status=ResourcePromotionStatus.CONSUMED,
            reasoning=proposal.reasoning,
            metadata=dict(proposal.metadata),
        )
        self._proposals[proposal_id] = updated
        return updated
