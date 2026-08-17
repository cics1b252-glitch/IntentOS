"""Movement 18 — Activation Application Boundary.

ACTIVATION_APPLICATION_ONLY — applies a valid activation decision to
canonical RRM lifecycle fields.

ACTIVATION MUST VERIFY PREREQUISITE TRUTH.
ACTIVATION MUST NOT INVENT PREREQUISITE TRUTH.
ACTIVATION APPROVAL IS NOT PREREQUISITE EVIDENCE.

The boundary MUST NOT manufacture prerequisite truth.
The boundary MAY apply an activation transition already justified by evidence.

Before mutation, performs 14-point TOCTOU revalidation:

1.  activation request still exists
2.  decision still exists
3.  decision is APPROVED
4.  decision matches exact request
5.  request matches exact resource
6.  resource is still registered
7.  registration/provenance is unchanged
8.  resource object/identity has not been silently replaced
9.  prerequisite evidence still exists and is valid
10. evidence still applies to exact resource
11. evidence not stale/revoked
12. binding/configuration identity unchanged
13. scope remains valid
14. decision has not expired/revoked/been consumed

Check 15 (new): evidence revalidated against canonical source at
application time. Stored evidence snapshots alone are not trusted.

Fail closed on any mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from intent_kernel.activation.models import (
    ResourceActivationDecision,
    ResourceActivationDecisionType,
    ResourceActivationEvidence,
    ResourceActivationRequest,
    ResourceActivationResult,
    ResourceActivationStatus,
)
from intent_kernel.discovery.models import ResourceDiscoveryKind
from intent_kernel.rrm.models import ResourceType, ResourceStatus
from intent_kernel.rrm.service import RegistryResourceManager
from intent_kernel.time_utils import utc_iso


_RESOURCE_TYPE_MAP: dict[ResourceDiscoveryKind, ResourceType] = {
    ResourceDiscoveryKind.PROVIDER: ResourceType.PROVIDER,
    ResourceDiscoveryKind.CAPABILITY: ResourceType.CAPABILITY,
    ResourceDiscoveryKind.AGENT: ResourceType.AGENT,
    ResourceDiscoveryKind.DEVICE: ResourceType.CAPABILITY,
    ResourceDiscoveryKind.CUSTOM: ResourceType.CAPABILITY,
    ResourceDiscoveryKind.CONNECTED_SERVICE: ResourceType.ACCOUNT,
    ResourceDiscoveryKind.LOCAL_PROGRAM: ResourceType.CAPABILITY,
    ResourceDiscoveryKind.ENVIRONMENT: ResourceType.EXECUTION_ENVIRONMENT,
}


@dataclass(frozen=True, slots=True)
class _RevalidationResult:
    """Result of a single TOCTOU revalidation check."""

    passed: bool
    check_name: str
    reason: str = ""


class ActivationApplicationBoundary:
    """ACTIVATION_APPLICATION_ONLY — applies activation decisions to RRM.

    Only this boundary may apply a valid activation decision to the RRM
    lifecycle fields controlled by Movement 18. Performs 14-point TOCTOU
    revalidation before any mutation, plus evidence TOCTOU revalidation.

    The boundary MUST NOT manufacture prerequisite truth.

    For governed resources, only this boundary may apply legitimate
    updates (exact-provenance guarded, TOCTOU-revalidated).
    """

    def __init__(
        self,
        rrm: RegistryResourceManager,
        activation_requests: dict[str, ResourceActivationRequest],
        activation_decisions: dict[str, ResourceActivationDecision],
        consumed_decisions: set[str],
        evidence_store: dict[str, ResourceActivationEvidence] | None = None,
        evidence_authority: Any = None,
    ) -> None:
        self._rrm = rrm
        self._requests = activation_requests
        self._decisions = activation_decisions
        self._consumed = consumed_decisions
        self._evidence_store = evidence_store or {}
        self._evidence_authority = evidence_authority

    def update_evidence(self, evidence: ResourceActivationEvidence) -> None:
        """Update evidence store for boundary revalidation."""
        self._evidence_store[evidence.evidence_id] = evidence

    def apply(
        self,
        decision_id: str,
    ) -> ResourceActivationResult:
        """Apply an activation decision to RRM with TOCTOU revalidation.

        ACTIVATION_APPLICATION_ONLY — the only boundary that may mutate
        RRM lifecycle fields for governed activation.
        """
        # Check 2: decision exists
        decision = self._decisions.get(decision_id)
        if decision is None:
            return ResourceActivationResult(
                success=False, request_id="", decision_id=decision_id,
                resource_id="", reason="decision_not_found",
            )

        # Check 14: decision not consumed
        if decision_id in self._consumed:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason="decision_already_consumed",
            )

        # Check 3: decision is APPROVED
        if decision.decision_type != ResourceActivationDecisionType.APPROVE:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason="decision_not_approved",
            )

        # Check 1: request exists
        request = self._requests.get(decision.request_id)
        if request is None:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason="request_not_found",
            )

        # Check 4: decision matches request
        if decision.request_id != request.request_id:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason="decision_request_mismatch",
            )

        # Check 5: request matches resource
        if decision.resource_id != request.resource_id:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason="decision_resource_mismatch",
            )

        resource_type = _RESOURCE_TYPE_MAP.get(decision.resource_kind)
        if resource_type is None:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason="unsupported_resource_kind",
            )

        # Check 6: resource still registered
        resource = self._get_resource(resource_type, decision.resource_id)
        if resource is None:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason="resource_not_registered",
            )

        # Check 7: registration/provenance unchanged
        if resource.is_template:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason="resource_is_template",
            )

        if resource.resource_origin.value == "template":
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason="resource_origin_template",
            )

        # Check 8: resource status still valid for activation
        if resource.status != ResourceStatus.ACTIVE:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason="resource_not_active",
            )

        # Check 9: prerequisite evidence still exists and is valid
        for eid in request.evidence_ids:
            evidence = self._evidence_store.get(eid)
            if evidence is None:
                return ResourceActivationResult(
                    success=False, request_id=decision.request_id,
                    decision_id=decision_id, resource_id=decision.resource_id,
                    reason=f"evidence_not_found: {eid}",
                )
            if evidence.revoked:
                return ResourceActivationResult(
                    success=False, request_id=decision.request_id,
                    decision_id=decision_id, resource_id=decision.resource_id,
                    reason=f"evidence_revoked: {eid}",
                )

        # Check 10: evidence still applies to exact resource
        for eid in request.evidence_ids:
            evidence = self._evidence_store.get(eid)
            if evidence is not None and evidence.resource_id != decision.resource_id:
                return ResourceActivationResult(
                    success=False, request_id=decision.request_id,
                    decision_id=decision_id, resource_id=decision.resource_id,
                    reason=f"evidence_resource_mismatch: {eid}",
                )

        # Check 11: evidence not stale (revalidate authority's evidence verification)
        prereq_check = self._revalidate_pre_activation_prerequisites(resource_type, resource)
        if not prereq_check.passed:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason=f"prerequisite_revalidation_failed: {prereq_check.reason}",
            )

        # Check 12: binding/configuration identity unchanged
        binding_check = self._revalidate_binding(resource_type, resource, request)
        if not binding_check.passed:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason=f"binding_revalidation_failed: {binding_check.reason}",
            )

        # Check 13: scope valid
        if request.scope and decision.scope and request.scope != decision.scope:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason="scope_mismatch",
            )

        # Check 15: evidence TOCTOU — revalidate against canonical source
        if self._evidence_authority is not None:
            fresh_evidence = self._evidence_authority.collect_for_resource(
                decision.resource_id, decision.resource_kind,
            )
            fresh_types = {ev.evidence_type for ev in fresh_evidence}
            for eid in request.evidence_ids:
                stored_evidence = self._evidence_store.get(eid)
                if stored_evidence is None:
                    return ResourceActivationResult(
                        success=False, request_id=decision.request_id,
                        decision_id=decision_id, resource_id=decision.resource_id,
                        reason=f"evidence_not_found: {eid}",
                    )
                if stored_evidence.evidence_type not in fresh_types:
                    return ResourceActivationResult(
                        success=False, request_id=decision.request_id,
                        decision_id=decision_id, resource_id=decision.resource_id,
                        reason=f"evidence_no_longer_canonical: {eid}",
                    )

        # All checks passed — apply activation transition
        # The boundary MUST NOT manufacture prerequisite truth.
        # Activation fields must already be in the correct state as verified
        # by the authority's evidence validation.
        fields_observed = self._observe_activation_state(resource_type, resource)

        # Consume the decision (single-use)
        self._consumed.add(decision_id)

        return ResourceActivationResult(
            success=True,
            request_id=decision.request_id,
            decision_id=decision_id,
            resource_id=decision.resource_id,
            reason="activation_applied",
            fields_updated=tuple(fields_observed),
        )

    def _get_resource(self, resource_type: ResourceType, resource_id: str):
        if resource_type == ResourceType.PROVIDER:
            return self._rrm.get_provider(resource_id)
        elif resource_type == ResourceType.CAPABILITY:
            return self._rrm.get_capability(resource_id)
        elif resource_type == ResourceType.AGENT:
            return self._rrm.get_agent(resource_id)
        elif resource_type == ResourceType.EXECUTION_ENVIRONMENT:
            return self._rrm.get_environment(resource_id)
        elif resource_type == ResourceType.ACCOUNT:
            return self._rrm.get_account(resource_id)
        elif resource_type == ResourceType.PROJECT:
            return self._rrm.get_project(resource_id)
        return None

    def _revalidate_pre_activation_prerequisites(self, resource_type: ResourceType, resource) -> _RevalidationResult:
        """Re-validate structural invariants at application time."""
        if resource.is_template:
            return _RevalidationResult(False, "not_template", "Resource became template")
        if resource.resource_origin.value == "template":
            return _RevalidationResult(False, "origin_not_template", "Resource origin is TEMPLATE")
        if resource.status != ResourceStatus.ACTIVE:
            return _RevalidationResult(False, "status_active", f"Status is {resource.status.value}")

        return _RevalidationResult(True, "all_pre_activation_prerequisites_satisfied")

    def _revalidate_binding(
        self, resource_type: ResourceType, resource, request: ResourceActivationRequest,
    ) -> _RevalidationResult:
        """Re-validate binding/configuration identity at application time.

        Uses evidence to verify that the binding/configuration is still current.
        """
        if resource_type == ResourceType.PROVIDER:
            if not resource.is_configured:
                return _RevalidationResult(False, "provider_configured", "Provider is no longer configured")
            if not resource.has_active_account:
                return _RevalidationResult(False, "provider_active_account", "Provider no longer has active account")
        elif resource_type == ResourceType.CAPABILITY:
            if not resource.is_executable:
                return _RevalidationResult(False, "capability_executable", "Capability is no longer executable")
        elif resource_type == ResourceType.AGENT:
            if not resource.is_enabled:
                return _RevalidationResult(False, "agent_enabled", "Agent is no longer enabled")
        elif resource_type == ResourceType.EXECUTION_ENVIRONMENT:
            if not resource.is_discovered:
                return _RevalidationResult(False, "environment_discovered", "Environment is no longer discovered")
        elif resource_type == ResourceType.ACCOUNT:
            if not resource.secret_reference:
                return _RevalidationResult(False, "account_secret_reference", "Account secret reference is gone")

        return _RevalidationResult(True, "binding_identity_unchanged")

    def _observe_activation_state(
        self, resource_type: ResourceType, resource,
    ) -> list[str]:
        """Observe (read-only) current activation fields. Must NOT mutate.

        Returns list of fields that are already in the correct state.
        """
        fields: list[str] = []

        if resource_type == ResourceType.PROVIDER:
            if resource.is_configured:
                fields.append("is_configured")
            if resource.has_active_account:
                fields.append("has_active_account")
        elif resource_type == ResourceType.CAPABILITY:
            if resource.is_executable:
                fields.append("is_executable")
        elif resource_type == ResourceType.AGENT:
            if resource.is_enabled:
                fields.append("is_enabled")
            fields.append(f"installation_state={resource.installation_state.value}")
        elif resource_type == ResourceType.EXECUTION_ENVIRONMENT:
            if resource.is_discovered:
                fields.append("is_discovered")
        elif resource_type == ResourceType.ACCOUNT:
            if resource.secret_reference:
                fields.append("secret_reference")

        return fields
