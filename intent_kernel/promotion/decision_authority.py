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
    ReRegistrationPrecondition,
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
        re_registration_precondition: ReRegistrationPrecondition | None = None,
    ) -> ResourcePromotionDecision:
        """Make a typed decision on a PENDING proposal.

        ``re_registration_precondition`` is optional. When provided, it
        immutably binds the exact retired predecessor (kind/id/lineage/
        generation) that this approval authorizes re-registration for. Ordinary
        first-time promotion decisions remain valid without it.
        """
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

        return self._record_decision(
            proposal,
            decision_type,
            decided_by=decided_by,
            reasoning=reasoning,
            re_registration_precondition=re_registration_precondition,
        )

    def decide_bootstrap(
        self,
        *,
        declaration: object,
        evidence: object,
        proposal_id: str,
        observed_pre_governed_generation: int,
        decided_by: str = "bootstrap",
        reasoning: str = "",
    ) -> ResourcePromotionDecision:
        """M31.3B-1B — certified bootstrap approval for an EXACT declaration.

        MODEL_AP_B. Approves first governance of the exact existing
        pre-governed canonical resource named by ``declaration``, grounded in
        the exact OBSERVED evidence. The observed pre-governed generation is a
        precondition for RRM's atomic first governance — the caller can never
        supply a resulting generation.

        APPROVAL_ONLY: records the approval decision and transitions the
        proposal to APPROVED. Does NOT register, mutate RRM, or mint lineage.
        """
        from intent_kernel.discovery.models import (
            ResourceDiscoveryEvidence,
            ResourceDiscoveryStatus,
        )
        from intent_kernel.promotion.models import FirstGovernancePrecondition

        if declaration is None:
            raise PromotionError("bootstrap declaration is required")
        if not isinstance(evidence, ResourceDiscoveryEvidence):
            raise PromotionError(
                "bootstrap evidence must be a ResourceDiscoveryEvidence"
            )
        if evidence.status is not ResourceDiscoveryStatus.OBSERVED:
            raise PromotionError(
                f"bootstrap evidence is {evidence.status.value}, not observed"
            )
        if evidence.resource_kind is not getattr(
            declaration, "discovery_kind", None
        ):
            raise PromotionError("bootstrap evidence kind does not match declaration")
        if evidence.resource_id != getattr(declaration, "resource_id", None):
            raise PromotionError("bootstrap evidence resource does not match declaration")
        if (
            not isinstance(observed_pre_governed_generation, int)
            or isinstance(observed_pre_governed_generation, bool)
            or observed_pre_governed_generation < 1
        ):
            raise PromotionError(
                "observed_pre_governed_generation must be a positive int (>=1), "
                "never a missing/legacy generation"
            )

        proposal = self._proposal_service.get_proposal(proposal_id)
        if proposal is None:
            raise PromotionError(f"Proposal not found: {proposal_id}")
        if proposal.status is not ResourcePromotionStatus.PENDING:
            raise PromotionError(
                f"Proposal is {proposal.status.value}, not pending"
            )
        if proposal.evidence_identity != evidence.discovery_id:
            raise PromotionError(
                "bootstrap proposal is not bound to the exact evidence"
            )
        if proposal.resource_id != evidence.resource_id:
            raise PromotionError(
                "bootstrap proposal resource does not match evidence"
            )
        if proposal.resource_kind is not evidence.resource_kind:
            raise PromotionError(
                "bootstrap proposal kind does not match evidence"
            )

        precondition = FirstGovernancePrecondition(
            resource_kind=declaration.resource_kind,
            resource_id=declaration.resource_id,
            expected_pre_governed_generation=observed_pre_governed_generation,
            expected_ungoverned_lineage=True,
        )

        return self._record_decision(
            proposal,
            ResourcePromotionDecisionType.APPROVE,
            decided_by=decided_by,
            reasoning=reasoning,
            first_governance_precondition=precondition,
        )

    def _record_decision(
        self,
        proposal: ResourcePromotionProposal,
        decision_type: ResourcePromotionDecisionType,
        *,
        decided_by: str,
        reasoning: str,
        re_registration_precondition: ReRegistrationPrecondition | None = None,
        first_governance_precondition: object | None = None,
    ) -> ResourcePromotionDecision:
        """Persist a typed decision and transition the proposal status."""
        proposal_id = proposal.proposal_id
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
            re_registration_precondition=re_registration_precondition,
            first_governance_precondition=first_governance_precondition,
        )

        self._decisions[decision_id] = decision

        # Transition proposal status
        if decision_type is ResourcePromotionDecisionType.APPROVE:
            updated_status = ResourcePromotionStatus.APPROVED
        else:
            updated_status = ResourcePromotionStatus.REJECTED
        updated = ResourcePromotionProposal(
            proposal_id=proposal_id,
            discovery_id=proposal.discovery_id,
            resource_id=proposal.resource_id,
            resource_kind=proposal.resource_kind,
            discovery_source=proposal.discovery_source,
            evidence_identity=proposal.evidence_identity,
            proposed_descriptor=dict(proposal.proposed_descriptor),
            requested_scope=proposal.requested_scope,
            created_at=proposal.created_at,
            status=updated_status,
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
