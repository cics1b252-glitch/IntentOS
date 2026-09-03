"""Movement 17 — Canonical Registration Boundary.

REGISTRATION_ONLY — translates approved proposals into RRM registration.

Only after valid proposal + valid approval may canonical registration occur.

It must NOT become:
  - availability authority;
  - eligibility authority;
  - authorization authority;
  - execution authority;
  - provider selection authority;
  - Mission authority.

RRM remains canonical authority for runtime availability/eligibility.

Cycle 4: This boundary generates canonical governed_registration_id for
each registered resource. The governed identity is bound to
resource_id + kind + proposal_id + decision_id and is NOT caller-controlled.
"""

from __future__ import annotations

from uuid import uuid4

from intent_kernel.discovery.models import ResourceDiscoveryStatus
from intent_kernel.promotion.decision_authority import ResourcePromotionDecisionAuthority
from intent_kernel.promotion.models import (
    ResourcePromotionDecisionType,
    ResourcePromotionResult,
    ResourcePromotionStatus,
    _PROHIBITED_PROPOSAL_FIELDS,
)
from intent_kernel.promotion.proposal_service import (
    PromotionError,
    ResourcePromotionProposalService,
)
from intent_kernel.time_utils import utc_iso


class CanonicalPromotionRegistrationBoundary:
    """Translates approved proposals into canonical RRM registration.

    REGISTRATION_ONLY — only callable after valid proposal + valid approval.
    """

    def __init__(
        self,
        proposal_service: ResourcePromotionProposalService,
        decision_authority: ResourcePromotionDecisionAuthority,
        rrm: object,
    ) -> None:
        self._proposals = proposal_service
        self._decisions = decision_authority
        self._rrm = rrm

    def register(
        self,
        proposal_id: str,
        decision_id: str,
        *,
        fresh: bool = True,
    ) -> ResourcePromotionResult:
        """Register an approved proposal into canonical RRM.

        Performs 10-point TOCTOU revalidation before any RRM mutation.
        If any check fails: FAIL CLOSED.
        """
        reg_at = utc_iso()

        # --- TOCTOU CHECK 1: proposal still exists ---
        proposal = self._proposals.get_proposal(proposal_id)
        if proposal is None:
            return ResourcePromotionResult(
                success=False,
                proposal_id=proposal_id,
                decision_id=decision_id,
                registration_type="",
                resource_id="",
                registered_at=reg_at,
                reason="proposal_not_found",
            )

        # --- TOCTOU CHECK 2: proposal still APPROVED ---
        if proposal.status is not ResourcePromotionStatus.APPROVED:
            return ResourcePromotionResult(
                success=False,
                proposal_id=proposal_id,
                decision_id=decision_id,
                registration_type="",
                resource_id=proposal.resource_id,
                registered_at=reg_at,
                reason=f"proposal_not_approved_{proposal.status.value}",
            )

        # --- TOCTOU CHECK 3: decision exists, is APPROVED, matches exact proposal ---
        decision = self._decisions.get_decision(decision_id)
        if decision is None:
            return ResourcePromotionResult(
                success=False,
                proposal_id=proposal_id,
                decision_id=decision_id,
                registration_type="",
                resource_id=proposal.resource_id,
                registered_at=reg_at,
                reason="decision_not_found",
            )
        if decision.decision_type is not ResourcePromotionDecisionType.APPROVE:
            return ResourcePromotionResult(
                success=False,
                proposal_id=proposal_id,
                decision_id=decision_id,
                registration_type="",
                resource_id=proposal.resource_id,
                registered_at=reg_at,
                reason="decision_not_approved",
            )
        if decision.proposal_id != proposal_id:
            return ResourcePromotionResult(
                success=False,
                proposal_id=proposal_id,
                decision_id=decision_id,
                registration_type="",
                resource_id=proposal.resource_id,
                registered_at=reg_at,
                reason="decision_proposal_mismatch",
            )

        # --- TOCTOU CHECK 4: decision not yet consumed ---
        if self._decisions.is_consumed(decision_id):
            return ResourcePromotionResult(
                success=False,
                proposal_id=proposal_id,
                decision_id=decision_id,
                registration_type="",
                resource_id=proposal.resource_id,
                registered_at=reg_at,
                reason="decision_already_consumed",
            )

        # --- TOCTOU CHECK 5: discovery evidence still exists ---
        evidence = self._proposals._discovery.get(proposal.discovery_id)  # noqa: SLF001
        if evidence is None:
            return ResourcePromotionResult(
                success=False,
                proposal_id=proposal_id,
                decision_id=decision_id,
                registration_type="",
                resource_id=proposal.resource_id,
                registered_at=reg_at,
                reason="evidence_not_found",
            )

        # --- TOCTOU CHECK 6: evidence identity matches proposal provenance ---
        if evidence.discovery_id != proposal.evidence_identity:
            return ResourcePromotionResult(
                success=False,
                proposal_id=proposal_id,
                decision_id=decision_id,
                registration_type="",
                resource_id=proposal.resource_id,
                registered_at=reg_at,
                reason="evidence_identity_mismatch",
            )

        # --- TOCTOU CHECK 7: evidence not revoked ---
        if evidence.status is ResourceDiscoveryStatus.REVOKED:
            return ResourcePromotionResult(
                success=False,
                proposal_id=proposal_id,
                decision_id=decision_id,
                registration_type="",
                resource_id=proposal.resource_id,
                registered_at=reg_at,
                reason="evidence_revoked",
            )

        # --- TOCTOU CHECK 8: evidence not stale (if freshness required) ---
        if fresh and evidence.status is ResourceDiscoveryStatus.STALE:
            return ResourcePromotionResult(
                success=False,
                proposal_id=proposal_id,
                decision_id=decision_id,
                registration_type="",
                resource_id=proposal.resource_id,
                registered_at=reg_at,
                reason="evidence_stale",
            )

        # --- TOCTOU CHECK 9: scope still matches ---
        if decision.scope != proposal.requested_scope:
            return ResourcePromotionResult(
                success=False,
                proposal_id=proposal_id,
                decision_id=decision_id,
                registration_type="",
                resource_id=proposal.resource_id,
                registered_at=reg_at,
                reason="scope_mismatch",
            )

        # Detection of the (optional) governed re-registration precondition.
        # When present, this approval authorizes re-registration of an EXACT
        # retired predecessor; the successor lineage B is RRM-sourced, never
        # boundary-minted.
        precondition = getattr(decision, "re_registration_precondition", None)

        # --- TOCTOU CHECK 10: no conflicting canonical resource ---
        # Re-registration defers active/pending lifecycle enforcement to RRM's
        # conditional_reregister_resource (RRM enforces state/lifecycle facts,
        # including ACTIVE_RESOURCE_CONFLICT / ALREADY_APPLIED / recovery). The
        # ordinary first-time promotion conflict gate applies only to fresh
        # registrations.
        if precondition is None:
            conflict = self._check_rrm_conflict(proposal)
            if conflict:
                return ResourcePromotionResult(
                    success=False,
                    proposal_id=proposal_id,
                    decision_id=decision_id,
                    registration_type="",
                    resource_id=proposal.resource_id,
                    registered_at=reg_at,
                    reason=conflict,
                )

        # --- ALL CHECKS PASSED: register in RRM ---
        if precondition is not None:
            result = self._rrm_reregister(proposal, decision, precondition)
            return result

        reg_type = self._rrm_register(proposal)
        if reg_type is None:
            return ResourcePromotionResult(
                success=False,
                proposal_id=proposal_id,
                decision_id=decision_id,
                registration_type="",
                resource_id=proposal.resource_id,
                registered_at=reg_at,
                reason="unsupported_resource_kind",
            )

        # --- Consume decision (single-use) ---
        self._decisions.consume(decision_id)

        # --- Transition proposal to CONSUMED ---
        self._proposals.transition_to_consumed(proposal_id)

        return ResourcePromotionResult(
            success=True,
            proposal_id=proposal_id,
            decision_id=decision_id,
            registration_type=reg_type,
            resource_id=proposal.resource_id,
            registered_at=reg_at,
            reason="registered",
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_rrm_conflict(self, proposal: object) -> str | None:
        """Check if a conflicting canonical resource already exists."""
        kind_val = getattr(proposal, "resource_kind", None)
        rid = getattr(proposal, "resource_id", "")
        kind_str = (getattr(kind_val, "value", "") if kind_val else "").lower()

        getter = None
        if kind_str == "provider":
            getter = getattr(self._rrm, "get_provider", None)
        elif kind_str == "capability":
            getter = getattr(self._rrm, "get_capability", None)
        elif kind_str == "agent":
            getter = getattr(self._rrm, "get_agent", None)
        elif kind_str == "environment":
            getter = getattr(self._rrm, "get_environment", None)

        if getter is None:
            return None

        existing = getter(rid)
        if existing is not None:
            return "conflicting_canonical_resource"
        return None

    def _kind_family_string(self, proposal: object) -> str:
        """Map proposal resource_kind to the RRM family registration string."""
        kind_str = (
            getattr(getattr(proposal, "resource_kind", None), "value", "")
        ).lower()
        if kind_str == "account":
            return "account"
        if kind_str == "project":
            return "project"
        return kind_str or ""

    def _rrm_reregister(self, proposal: object, decision: object, precondition: object):
        """Route a re-registration approval to RRM (sole lineage authority).

        MRM 31.2B-2C: successor lineage B is RRM-generated and RRM-written
        (consumption WRITE 1, then active B WRITE 2) atomically under the RRM
        lock. The boundary does NOT mint lineage for re-registration and does
        NOT supply successor lineage / resulting generation.

        The decision is consumed ONLY after successful RRM re-registration /
        recovery / already-applied. On failure the decision remains retryable.
        """
        from intent_kernel.promotion.models import ReRegistrationPrecondition
        from intent_kernel.rrm.models import (
            ConditionalReregistrationOutcome,
            ConditionalReregistrationRequest,
        )

        if not isinstance(precondition, ReRegistrationPrecondition):
            return ResourcePromotionResult(
                success=False,
                proposal_id=getattr(proposal, "proposal_id", ""),
                decision_id=getattr(decision, "decision_id", ""),
                registration_type=self._kind_family_string(proposal),
                resource_id=getattr(proposal, "resource_id", ""),
                reason="invalid_re_registration_precondition",
            )

        proposal_id = getattr(proposal, "proposal_id", "")
        decision_id = getattr(decision, "decision_id", "")

        request = ConditionalReregistrationRequest(
            resource_kind=precondition.resource_kind,
            resource_id=precondition.resource_id,
            predecessor_governed_registration_id=(
                precondition.retired_governed_registration_id
            ),
            predecessor_observed_generation=precondition.retired_observed_generation,
            proposal_id=proposal_id,
            decision_id=decision_id,
        )

        from intent_kernel.promotion.models import ResourcePromotionResult

        rr = self._rrm.conditional_reregister_resource(
            request,
            materialization_descriptor=getattr(
                proposal, "proposed_descriptor", {}
            ),
        )

        outcome = getattr(rr, "outcome", None)
        success_outcomes = (
            ConditionalReregistrationOutcome.REREGISTERED,
            ConditionalReregistrationOutcome.REREGISTRATION_RECOVERED,
            ConditionalReregistrationOutcome.REREGISTRATION_ALREADY_APPLIED,
        )
        if outcome in success_outcomes:
            self._decisions.consume(decision_id)
            self._proposals.transition_to_consumed(proposal_id)
            reason_map = {
                ConditionalReregistrationOutcome.REREGISTERED: "reregistered",
                ConditionalReregistrationOutcome.REREGISTRATION_RECOVERED: (
                    "reregistration_recovered"
                ),
                ConditionalReregistrationOutcome.REREGISTRATION_ALREADY_APPLIED: (
                    "reregistration_already_applied"
                ),
            }
            return ResourcePromotionResult(
                success=True,
                proposal_id=proposal_id,
                decision_id=decision_id,
                registration_type=self._kind_family_string(proposal),
                resource_id=request.resource_id,
                reason=reason_map.get(outcome, "reregistered"),
                governed_registration_id=(
                    getattr(rr, "successor_governed_registration_id", "") or ""
                ),
                observed_generation=(
                    getattr(rr, "successor_observed_generation", 0) or 0
                ),
                re_registration=True,
            )

        return ResourcePromotionResult(
            success=False,
            proposal_id=proposal_id,
            decision_id=decision_id,
            registration_type=self._kind_family_string(proposal),
            resource_id=request.resource_id,
            reason=(getattr(outcome, "value", "") or "reregistration_failed"),
            re_registration=True,
        )

    def _rrm_register(self, proposal: object) -> str | None:
        """Translate proposal into RRM registration. Returns reg type or None.

        Cycle 4: Generates canonical governed_registration_id bound to
        resource_id + kind + proposal_id + decision_id. Caller cannot
        control governed identity.
        """
        from intent_kernel.rrm.models import (
            AccountResource,
            AgentResource,
            AvailabilitySource,
            CapabilityResource,
            ExecutionEnvironmentResource,
            ProviderResource,
            ResourceOrigin,
            ResourceStatus,
        )

        kind_val = getattr(proposal, "resource_kind", None)
        kind_str = (getattr(kind_val, "value", "") if kind_val else "").lower()
        rid = getattr(proposal, "resource_id", "")
        desc = getattr(proposal, "proposed_descriptor", {})
        scope = getattr(proposal, "requested_scope", "global")
        proposal_id = getattr(proposal, "proposal_id", "")

        canonical_reg_id = f"registration_{uuid4().hex[:12]}"

        base_meta: dict[str, object] = {
            "promotion_scope": scope,
            "promotion_via": "canonical_promotion_boundary",
            "canonical_registration_id": canonical_reg_id,
        }

        if kind_str == "provider":
            resource = ProviderResource(
                provider_id=rid,
                name=desc.get("display_name", rid),
                resource_origin=ResourceOrigin.USER_REGISTRATION,
                availability_source=AvailabilitySource.UNKNOWN,
                is_template=False,
                is_configured=False,
                has_active_account=False,
                status=ResourceStatus.ACTIVE,
                governed_registration_id=canonical_reg_id,
                metadata=base_meta,
            )
            self._rrm.register_provider(resource)
            if hasattr(self._rrm, "mark_governed"):
                self._rrm.mark_governed(rid, canonical_reg_id)
            return "provider"

        if kind_str == "capability":
            resource = CapabilityResource(
                capability_id=rid,
                name=desc.get("display_name", rid),
                resource_origin=ResourceOrigin.USER_REGISTRATION,
                availability_source=AvailabilitySource.UNKNOWN,
                is_template=False,
                is_executable=False,
                status=ResourceStatus.ACTIVE,
                tags=tuple(desc.get("capability_claims", [])),
                governed_registration_id=canonical_reg_id,
                metadata=base_meta,
            )
            self._rrm.register_capability(resource)
            if hasattr(self._rrm, "mark_governed"):
                self._rrm.mark_governed(rid, canonical_reg_id)
            return "capability"

        if kind_str == "agent":
            resource = AgentResource(
                agent_id=rid,
                name=desc.get("display_name", rid),
                resource_origin=ResourceOrigin.USER_REGISTRATION,
                availability_source=AvailabilitySource.UNKNOWN,
                is_template=False,
                is_enabled=False,
                installation_state=None,
                status=ResourceStatus.ACTIVE,
                governed_registration_id=canonical_reg_id,
                metadata=base_meta,
            )
            self._rrm.register_agent(resource)
            if hasattr(self._rrm, "mark_governed"):
                self._rrm.mark_governed(rid, canonical_reg_id)
            return "agent"

        if kind_str == "environment":
            resource = ExecutionEnvironmentResource(
                environment_id=rid,
                type=None,
                resource_origin=ResourceOrigin.USER_REGISTRATION,
                availability_source=AvailabilitySource.UNKNOWN,
                is_template=False,
                is_discovered=False,
                status=ResourceStatus.ACTIVE,
                governed_registration_id=canonical_reg_id,
                metadata=base_meta,
            )
            self._rrm.register_environment(resource)
            if hasattr(self._rrm, "mark_governed"):
                self._rrm.mark_governed(rid, canonical_reg_id)
            return "environment"

        # All other kinds (tool, device, custom, connected_service, etc.)
        # map to CapabilityResource — no dedicated RRM type exists for them.
        resource = CapabilityResource(
            capability_id=rid,
            name=desc.get("display_name", rid),
            resource_origin=ResourceOrigin.USER_REGISTRATION,
            availability_source=AvailabilitySource.UNKNOWN,
            is_template=False,
            is_executable=False,
            status=ResourceStatus.ACTIVE,
            tags=tuple(desc.get("capability_claims", [])),
            governed_registration_id=canonical_reg_id,
            metadata={**base_meta, "discovery_kind": kind_str},
        )
        self._rrm.register_capability(resource)
        if hasattr(self._rrm, "mark_governed"):
            self._rrm.mark_governed(rid, canonical_reg_id)
        return "capability"

        return None
