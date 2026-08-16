"""Movement 17 — Governed Resource Promotion Service.

Orchestrates the full governed promotion pipeline:

  DISCOVERY EVIDENCE
  → PROPOSAL
  → TYPED DECISION
  → TOCTOU REVALIDATION
  → CANONICAL REGISTRATION
  → RRM

No stage may impersonate another.
"""

from __future__ import annotations

from intent_kernel.discovery.service import CanonicalResourceDiscoveryService
from intent_kernel.promotion.decision_authority import ResourcePromotionDecisionAuthority
from intent_kernel.promotion.models import (
    ResourcePromotionDecisionType,
    ResourcePromotionResult,
)
from intent_kernel.promotion.proposal_service import (
    PromotionError,
    ResourcePromotionProposalService,
)
from intent_kernel.promotion.registration_boundary import (
    CanonicalPromotionRegistrationBoundary,
)


class CanonicalResourcePromotionService:
    """Orchestrates the governed promotion pipeline.

    ORCHESTRATION_ONLY — delegates to sub-services; contains no
    independent mutation logic.
    """

    def __init__(
        self,
        discovery_service: CanonicalResourceDiscoveryService,
        rrm: object,
    ) -> None:
        self._discovery = discovery_service
        self._rrm = rrm
        self._proposal_service = ResourcePromotionProposalService(discovery_service)
        self._decision_authority = ResourcePromotionDecisionAuthority(
            self._proposal_service,
        )
        self._registration_boundary = CanonicalPromotionRegistrationBoundary(
            self._proposal_service,
            self._decision_authority,
            rrm,
        )

    # ------------------------------------------------------------------
    # Sub-service accessors (read-only)
    # ------------------------------------------------------------------

    @property
    def proposals(self) -> ResourcePromotionProposalService:
        return self._proposal_service

    @property
    def decisions(self) -> ResourcePromotionDecisionAuthority:
        return self._decision_authority

    @property
    def registration(self) -> CanonicalPromotionRegistrationBoundary:
        return self._registration_boundary

    # ------------------------------------------------------------------
    # Convenience entry points
    # ------------------------------------------------------------------

    def create_proposal(
        self,
        discovery_id: str,
        *,
        requested_scope: str = "global",
        reasoning: str = "",
        metadata: dict[str, object] | None = None,
    ):
        """Create a promotion proposal from discovery evidence."""
        return self._proposal_service.create_proposal(
            discovery_id,
            requested_scope=requested_scope,
            reasoning=reasoning,
            metadata=metadata,
        )

    def decide_proposal(
        self,
        proposal_id: str,
        decision_type: ResourcePromotionDecisionType,
        *,
        decided_by: str = "system",
        reasoning: str = "",
    ):
        """Make a typed decision on a proposal."""
        return self._decision_authority.decide(
            proposal_id,
            decision_type,
            decided_by=decided_by,
            reasoning=reasoning,
        )

    def promote(
        self,
        proposal_id: str,
        decision_id: str,
        *,
        fresh: bool = True,
    ) -> ResourcePromotionResult:
        """Full promotion: validate proposal + decision, register in RRM."""
        return self._registration_boundary.register(
            proposal_id,
            decision_id,
            fresh=fresh,
        )
