"""Movement 18 — Canonical Activation Evidence Authority.

EVIDENCE_VALIDATION_ONLY — validates every submitted evidence object
against live canonical sources before storing/using it.

EVIDENCE OBJECT != TRUSTED EVIDENCE
CALLER ASSERTION != CANONICAL SOURCE OF TRUTH
ACTIVATION APPROVAL != PREREQUISITE EVIDENCE

A public caller must NOT be able to construct arbitrary
ResourceActivationEvidence and have the activation authority trust it
as canonical prerequisite truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intent_kernel.activation.models import (
    ActivationEvidenceType,
    ResourceActivationEvidence,
)
from intent_kernel.discovery.models import ResourceDiscoveryKind
from intent_kernel.rrm.models import ResourceType
from intent_kernel.rrm.service import RegistryResourceManager
from intent_kernel.time_utils import utc_iso


@dataclass(frozen=True, slots=True)
class EvidenceValidationResult:
    """Result of validating a single evidence object."""

    valid: bool
    evidence_id: str
    reason: str = ""


class CanonicalActivationEvidenceAuthority:
    """EVIDENCE_VALIDATION_ONLY — validates evidence against canonical sources.

    This authority validates every submitted evidence object against
    live canonical state before accepting it as activation evidence.

    CALLER ASSERTION != CANONICAL SOURCE OF TRUTH.
    """

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

    def __init__(
        self,
        rrm: RegistryResourceManager,
        provider_manager: Any = None,
        capability_registry: Any = None,
    ) -> None:
        self._rrm = rrm
        self._provider_manager = provider_manager
        self._capability_registry = capability_registry
        self._validated_evidence: dict[str, ResourceActivationEvidence] = {}

    def validate_and_store(
        self,
        evidence: ResourceActivationEvidence,
    ) -> EvidenceValidationResult:
        """Validate evidence against canonical sources and store if valid.

        Every evidence object must be validated against the live canonical
        source before it can be used for activation.
        """
        if evidence.revoked:
            return EvidenceValidationResult(
                valid=False,
                evidence_id=evidence.evidence_id,
                reason="evidence_revoked",
            )

        resource_type = self._RESOURCE_TYPE_MAP.get(evidence.resource_kind)
        if resource_type is None:
            return EvidenceValidationResult(
                valid=False,
                evidence_id=evidence.evidence_id,
                reason="unsupported_resource_kind",
            )

        resource = self._get_resource(resource_type, evidence.resource_id)
        if resource is None:
            return EvidenceValidationResult(
                valid=False,
                evidence_id=evidence.evidence_id,
                reason="resource_not_registered",
            )

        validation = self._validate_evidence_against_source(
            evidence, resource_type, resource,
        )

        if validation.valid:
            self._validated_evidence[evidence.evidence_id] = evidence

        return validation

    def get_validated_evidence(self, evidence_id: str) -> ResourceActivationEvidence | None:
        return self._validated_evidence.get(evidence_id)

    def get_all_validated(self) -> dict[str, ResourceActivationEvidence]:
        return dict(self._validated_evidence)

    def _validate_evidence_against_source(
        self,
        evidence: ResourceActivationEvidence,
        resource_type: ResourceType,
        resource,
    ) -> EvidenceValidationResult:
        """Validate evidence against the canonical source for its type."""

        if evidence.evidence_type == ActivationEvidenceType.PROVIDER_CONFIGURATION:
            return self._validate_provider_configuration(evidence, resource)
        elif evidence.evidence_type == ActivationEvidenceType.PROVIDER_ACCOUNT:
            return self._validate_provider_account(evidence, resource)
        elif evidence.evidence_type == ActivationEvidenceType.CAPABILITY_EXECUTABLE:
            return self._validate_capability_executable(evidence, resource)
        elif evidence.evidence_type == ActivationEvidenceType.AGENT_IDENTITY:
            return self._validate_agent_identity(evidence, resource)
        elif evidence.evidence_type == ActivationEvidenceType.ENVIRONMENT_DISCOVERY:
            return self._validate_environment_discovery(evidence, resource)
        elif evidence.evidence_type == ActivationEvidenceType.ACCOUNT_SECRET:
            return self._validate_account_secret(evidence, resource)

        return EvidenceValidationResult(
            valid=False,
            evidence_id=evidence.evidence_id,
            reason="unknown_evidence_type",
        )

    def _validate_provider_configuration(
        self, evidence: ResourceActivationEvidence, resource,
    ) -> EvidenceValidationResult:
        """Validate provider configuration evidence against canonical state.

        Evidence is valid only if:
        - resource.is_configured is True in canonical RRM
        - binding identity matches if provided
        """
        if not resource.is_configured:
            return EvidenceValidationResult(
                valid=False,
                evidence_id=evidence.evidence_id,
                reason="provider_not_configured_in_canonical_source",
            )

        if evidence.binding_identity:
            if self._provider_manager is not None:
                if evidence.resource_id not in self._provider_manager.available:
                    return EvidenceValidationResult(
                        valid=False,
                        evidence_id=evidence.evidence_id,
                        reason="provider_binding_not_in_manager",
                    )

        return EvidenceValidationResult(
            valid=True,
            evidence_id=evidence.evidence_id,
        )

    def _validate_provider_account(
        self, evidence: ResourceActivationEvidence, resource,
    ) -> EvidenceValidationResult:
        """Validate provider active-account evidence against canonical state."""
        if not resource.has_active_account:
            return EvidenceValidationResult(
                valid=False,
                evidence_id=evidence.evidence_id,
                reason="provider_no_active_account_in_canonical_source",
            )

        return EvidenceValidationResult(
            valid=True,
            evidence_id=evidence.evidence_id,
        )

    def _validate_capability_executable(
        self, evidence: ResourceActivationEvidence, resource,
    ) -> EvidenceValidationResult:
        """Validate capability executable evidence against canonical registry.

        Evidence must reference an exact binding identity from the canonical
        capability registry.
        """
        if not resource.is_executable:
            return EvidenceValidationResult(
                valid=False,
                evidence_id=evidence.evidence_id,
                reason="capability_not_executable_in_canonical_source",
            )

        if evidence.binding_identity and self._capability_registry is not None:
            binding_found = False
            for cap_name, registrations in self._capability_registry._registrations.items():
                for reg in registrations:
                    if reg.binding_identity == evidence.binding_identity:
                        binding_found = True
                        break
                if binding_found:
                    break
            if not binding_found:
                return EvidenceValidationResult(
                    valid=False,
                    evidence_id=evidence.evidence_id,
                    reason="binding_identity_not_in_canonical_registry",
                )

        return EvidenceValidationResult(
            valid=True,
            evidence_id=evidence.evidence_id,
        )

    def _validate_agent_identity(
        self, evidence: ResourceActivationEvidence, resource,
    ) -> EvidenceValidationResult:
        """Validate agent identity evidence against canonical state."""
        if not resource.is_enabled:
            return EvidenceValidationResult(
                valid=False,
                evidence_id=evidence.evidence_id,
                reason="agent_not_enabled_in_canonical_source",
            )

        from intent_kernel.rrm.models import AgentInstallationState
        valid_states = (
            AgentInstallationState.INSTALLED,
            AgentInstallationState.ENABLED,
            AgentInstallationState.AVAILABLE,
        )
        if resource.installation_state not in valid_states:
            return EvidenceValidationResult(
                valid=False,
                evidence_id=evidence.evidence_id,
                reason=f"agent_installation_state_invalid: {resource.installation_state.value}",
            )

        return EvidenceValidationResult(
            valid=True,
            evidence_id=evidence.evidence_id,
        )

    def _validate_environment_discovery(
        self, evidence: ResourceActivationEvidence, resource,
    ) -> EvidenceValidationResult:
        """Validate environment discovery evidence against canonical state."""
        if not resource.is_discovered:
            return EvidenceValidationResult(
                valid=False,
                evidence_id=evidence.evidence_id,
                reason="environment_not_discovered_in_canonical_source",
            )

        return EvidenceValidationResult(
            valid=True,
            evidence_id=evidence.evidence_id,
        )

    def _validate_account_secret(
        self, evidence: ResourceActivationEvidence, resource,
    ) -> EvidenceValidationResult:
        """Validate account secret reference evidence against canonical state."""
        if not resource.secret_reference:
            return EvidenceValidationResult(
                valid=False,
                evidence_id=evidence.evidence_id,
                reason="account_no_secret_reference_in_canonical_source",
            )

        return EvidenceValidationResult(
            valid=True,
            evidence_id=evidence.evidence_id,
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
