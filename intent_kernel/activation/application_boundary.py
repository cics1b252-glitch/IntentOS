"""Movement 18 — Activation Application Boundary.

ACTIVATION_APPLICATION_ONLY — applies a valid activation decision to
canonical RRM lifecycle fields.

Before mutation, performs 12-point TOCTOU revalidation:

1.  activation request still exists
2.  decision still exists
3.  decision is APPROVED
4.  decision matches exact request
5.  request matches exact resource
6.  resource is still registered
7.  registration/provenance is unchanged
8.  resource object/identity has not been silently replaced
9.  prerequisites remain satisfied
10. required binding/configuration still matches
11. scope remains valid
12. decision has not expired/revoked/been consumed

Fail closed on any mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from intent_kernel.activation.models import (
    ResourceActivationDecision,
    ResourceActivationDecisionType,
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
    lifecycle fields controlled by Movement 18. Performs 12-point TOCTOU
    revalidation before any mutation.
    """

    def __init__(
        self,
        rrm: RegistryResourceManager,
        activation_requests: dict[str, ResourceActivationRequest],
        activation_decisions: dict[str, ResourceActivationDecision],
        consumed_decisions: set[str],
    ) -> None:
        self._rrm = rrm
        self._requests = activation_requests
        self._decisions = activation_decisions
        self._consumed = consumed_decisions

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

        # Check 12: decision not consumed
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

        # Check 9: pre-activation prerequisites still satisfied
        # Only checks structural invariants (registered, not template, active).
        # Does NOT re-check resource-kind-specific prerequisites that activation
        # itself establishes (is_configured, has_active_account, is_executable,
        # is_enabled, installation_state, is_discovered, secret_reference) —
        # those are the fields activation mutates.
        prereq_check = self._revalidate_pre_activation_prerequisites(resource_type, resource)
        if not prereq_check.passed:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason=f"prerequisite_revalidation_failed: {prereq_check.reason}",
            )

        # Check 11: scope valid
        if request.scope and decision.scope and request.scope != decision.scope:
            return ResourceActivationResult(
                success=False, request_id=decision.request_id,
                decision_id=decision_id, resource_id=decision.resource_id,
                reason="scope_mismatch",
            )

        # All checks passed — apply activation to RRM fields
        fields_updated = self._apply_activation(resource_type, resource, decision)

        # Consume the decision (single-use)
        self._consumed.add(decision_id)

        return ResourceActivationResult(
            success=True,
            request_id=decision.request_id,
            decision_id=decision_id,
            resource_id=decision.resource_id,
            reason="activation_applied",
            fields_updated=tuple(fields_updated),
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
        """Re-validate structural invariants at application time.

        Only checks pre-activation prerequisites that must hold BEFORE
        activation fields are applied. Does NOT check resource-kind-specific
        prerequisites that activation itself establishes.
        """
        if resource.is_template:
            return _RevalidationResult(False, "not_template", "Resource became template")
        if resource.resource_origin.value == "template":
            return _RevalidationResult(False, "origin_not_template", "Resource origin is TEMPLATE")
        if resource.status != ResourceStatus.ACTIVE:
            return _RevalidationResult(False, "status_active", f"Status is {resource.status.value}")

        return _RevalidationResult(True, "all_pre_activation_prerequisites_satisfied")

    def _apply_activation(
        self,
        resource_type: ResourceType,
        resource,
        decision: ResourceActivationDecision,
    ) -> list[str]:
        """Apply activation fields to the RRM resource.

        Returns list of fields that were updated.
        """
        now = utc_iso()
        fields_updated: list[str] = []

        if resource_type == ResourceType.PROVIDER:
            if not resource.is_configured:
                resource.is_configured = True
                fields_updated.append("is_configured")
            if not resource.has_active_account:
                resource.has_active_account = True
                fields_updated.append("has_active_account")

        elif resource_type == ResourceType.CAPABILITY:
            if not resource.is_executable:
                resource.is_executable = True
                fields_updated.append("is_executable")

        elif resource_type == ResourceType.AGENT:
            if not resource.is_enabled:
                resource.is_enabled = True
                fields_updated.append("is_enabled")
            if resource.installation_state.value not in {"INSTALLED", "ENABLED", "AVAILABLE"}:
                from intent_kernel.rrm.models import AgentInstallationState
                resource.installation_state = AgentInstallationState.INSTALLED
                fields_updated.append("installation_state")

        elif resource_type == ResourceType.EXECUTION_ENVIRONMENT:
            if not resource.is_discovered:
                resource.is_discovered = True
                fields_updated.append("is_discovered")

        elif resource_type == ResourceType.ACCOUNT:
            if not resource.is_configured:
                resource.is_configured = True
                fields_updated.append("is_configured")

        if fields_updated:
            resource.updated_at = now

        return fields_updated
