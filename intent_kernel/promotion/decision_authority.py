"""Movement 17 — Promotion Decision Authority.

APPROVAL_ONLY — typed promotion decisions.

A proposal must require an explicit decision before canonical registration.
Approval must be:
  - proposal-specific;
  - evidence-specific;
  - resource-specific;
  - scope-specific where applicable;
  - non-transferable;
  - single-use;
  - auditable.

Approval of Proposal A must never authorize Proposal B.
Approval of Resource A must never authorize Resource B sharing the same name.
Same logical resource ID with different evidence identity must not silently
inherit approval.
"""

from __future__ import annotations

from uuid import uuid4

from intent_kernel.promotion.models import (
    ResourcePromotionDecision,
    ResourcePromotionDecisionType,
    ResourcePromotionProposal,
    ResourcePromotionStatus,
)
from intent_kernel.promotion.proposal_service import (
    PromotionError,
    ResourcePromotionProposalService,
)
from intent_kernel.time_utils import utc_iso


class ResourcePromotionDecisionAuthority:
    """Typed promotion decision boundary.

    APPROVAL_ONLY — may NOT mutate RRM, register, execute, invoke.
    """

    def __init__(
        self,
        proposal_service: ResourcePromotionProposalService,
    ) -> None:
        self._proposal_service = proposal_service
        self._decisions: dict[str, ResourcePromotionDecision] = {}
        self._consumed: set[str] = set()

    # ------------------------------------------------------------------
    # READ
    # ------------------------------------------------------------------

    def get_decision(self, decision_id: str) -> ResourcePromotionDecision | None:
        return self._decisions.get(decision_id)

    def is_consumed(self, decision_id: str) -> bool:
        return decision_id in self._consumed

    @property
    def count(self) -> int:
        return len(self._decisions)

    # ------------------------------------------------------------------
    # WRITE — stores decisions, transitions proposal status
    # ------------------------------------------------------------------

    def decide(
        self,
        proposal_id: str,
        decision_type: ResourcePromotionDecisionType,
        *,
        decided_by: str = "system",
        reasoning: str = "",
    ) -> ResourcePromotionDecision:
        """Make a typed decision on a PENDING proposal."""
        proposal = self._proposal_service.get_proposal(proposal_id)
        if proposal is None:
            raise PromotionError(f"Proposal not found: {proposal_id}")
        if proposal.status is not ResourcePromotionStatus.PENDING:
            raise PromotionError(
                f"Proposal is {proposal.status.value}, not pending"
            )

        # Reject unknown decision types (str enum pseudo-members bypass 'in')
        dt_val = getattr(decision_type, "value", decision_type)
        if dt_val not in {e.value for e in ResourcePromotionDecisionType}:
            raise PromotionError(
                f"Unknown decision type: {dt_val!r}"
            )

        decision_id = f"dec-{uuid4().hex}"

        decision = ResourcePromotionDecision(
            decision_id=decision_id,
            proposal_id=proposal_id,
            evidence_identity=proposal.evidence_identity,
            decision_type=decision_type,
            decided_at=utc_iso(),
            decided_by=decided_by,
            reasoning=reasoning,
            scope=proposal.requested_scope,
        )

        self._decisions[decision_id] = decision

        # Transition proposal status
        if decision_type is ResourcePromotionDecisionType.APPROVE:
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
                status=ResourcePromotionStatus.APPROVED,
                reasoning=proposal.reasoning,
                metadata=dict(proposal.metadata),
            )
        else:
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
                status=ResourcePromotionStatus.REJECTED,
                reasoning=proposal.reasoning,
                metadata=dict(proposal.metadata),
            )

        # Store the updated proposal (replaces the original in the proposal service)
        self._proposal_service._proposals[proposal_id] = updated  # noqa: SLF001

        return decision

    def consume(self, decision_id: str) -> None:
        """Mark a decision as consumed (single-use)."""
        if decision_id not in self._decisions:
            raise PromotionError(f"Decision not found: {decision_id}")
        if decision_id in self._consumed:
            raise PromotionError(
                f"Decision already consumed: {decision_id}"
            )
        self._consumed.add(decision_id)
