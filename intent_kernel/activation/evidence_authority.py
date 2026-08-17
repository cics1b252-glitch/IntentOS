"""Movement 18 — Canonical Activation Evidence Authority.

EVIDENCE_COLLECTION_ONLY — derives activation evidence from canonical
sources. Callers CANNOT construct arbitrary ResourceActivationEvidence
and have it accepted as canonical prerequisite truth.

EVIDENCE OBJECT != TRUSTED EVIDENCE
CALLER ASSERTION != CANONICAL SOURCE OF TRUTH
ACTIVATION APPROVAL != PREREQUISITE EVIDENCE

collect_for_resource() produces evidence by querying the canonical
source directly. Only collect_for_resource() produces TRUSTED evidence.

validate_and_store() is COMPATIBILITY_ONLY / TEST_ONLY — it validates
caller-provided evidence against canonical sources but does NOT grant
it trusted status. Trusted evidence is ONLY produced by
collect_for_resource().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

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
    """EVIDENCE_COLLECTION_ONLY — derives evidence from canonical sources.

    This authority produces activation evidence by querying the canonical
    source directly. Callers cannot submit arbitrary evidence objects
    and have them accepted as truth.

    Only collect_for_resource() produces TRUSTED evidence stored in the
    canonical evidence trust store. validate_and_store() is
    COMPATIBILITY_ONLY / TEST_ONLY and does NOT produce trusted evidence.

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
        self._collected_evidence: dict[str, ResourceActivationEvidence] = {}
        self._compatibility_evidence: dict[str, ResourceActivationEvidence] = {}

    # ------------------------------------------------------------------
    # Primary API — derive evidence from canonical sources
    # ------------------------------------------------------------------

    def collect_for_resource(
        self,
        resource_id: str,
        resource_kind: ResourceDiscoveryKind,
    ) -> list[ResourceActivationEvidence]:
        """Derive ALL valid prerequisite evidence for a resource from canonical sources.

        This is the ONLY trusted entry point. Callers do NOT construct
        evidence objects — the authority derives them by querying the
        canonical source directly.

        ALL evidence produced by this method is marked as TRUSTED.
        """
        resource_type = self._RESOURCE_TYPE_MAP.get(resource_kind)
        if resource_type is None:
            return []

        resource = self._get_resource(resource_type, resource_id)
        if resource is None:
            return []

        evidence_list: list[ResourceActivationEvidence] = []

        if resource_type == ResourceType.PROVIDER:
            evidence_list.extend(self._collect_provider_evidence(resource, resource_id, resource_kind))
        elif resource_type == ResourceType.CAPABILITY:
            evidence_list.extend(self._collect_capability_evidence(resource, resource_id, resource_kind))
        elif resource_type == ResourceType.AGENT:
            evidence_list.extend(self._collect_agent_evidence(resource, resource_id, resource_kind))
        elif resource_type == ResourceType.EXECUTION_ENVIRONMENT:
            evidence_list.extend(self._collect_environment_evidence(resource, resource_id, resource_kind))
        elif resource_type == ResourceType.ACCOUNT:
            evidence_list.extend(self._collect_account_evidence(resource, resource_id, resource_kind))

        for ev in evidence_list:
            self._collected_evidence[ev.evidence_id] = ev

        return evidence_list

    def get_collected_evidence(self, evidence_id: str) -> ResourceActivationEvidence | None:
        return self._collected_evidence.get(evidence_id)

    def get_all_collected(self) -> dict[str, ResourceActivationEvidence]:
        return dict(self._collected_evidence)

    def is_evidence_trusted(self, evidence_id: str) -> bool:
        """Check if an evidence object is in the canonical trusted store."""
        return evidence_id in self._collected_evidence

    # ------------------------------------------------------------------
    # Backward-compatible entry point — COMPATIBILITY_ONLY / TEST_ONLY
    # ------------------------------------------------------------------

    def validate_and_store(
        self,
        evidence: ResourceActivationEvidence,
    ) -> EvidenceValidationResult:
        """Validate evidence against canonical sources. COMPATIBILITY_ONLY.

        Retained for backward compatibility and test infrastructure only.
        Does NOT grant evidence trusted status. Does NOT store in the
        canonical evidence trust store.

        For production canonical evidence: use collect_for_resource().
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
            self._compatibility_evidence[evidence.evidence_id] = evidence

        return validation

    def get_validated_evidence(self, evidence_id: str) -> ResourceActivationEvidence | None:
        return self._compatibility_evidence.get(evidence_id)

    def get_all_validated(self) -> dict[str, ResourceActivationEvidence]:
        return dict(self._compatibility_evidence)

    # ------------------------------------------------------------------
    # Canonical evidence producers — derive from source, not caller
    # ------------------------------------------------------------------

    def _collect_provider_evidence(
        self, resource, resource_id: str, resource_kind: ResourceDiscoveryKind,
    ) -> list[ResourceActivationEvidence]:
        """Derive provider prerequisite evidence from canonical source."""
        evidence_list: list[ResourceActivationEvidence] = []
        ts = utc_iso()

        if resource.is_configured:
            binding = ""
            if self._provider_manager is not None:
                if resource_id in getattr(self._provider_manager, "available", {}):
                    binding = f"provider-manager:{resource_id}"

            evidence_list.append(ResourceActivationEvidence(
                evidence_id=f"ev-{uuid4().hex[:12]}",
                resource_id=resource_id,
                resource_kind=resource_kind,
                evidence_type=ActivationEvidenceType.PROVIDER_CONFIGURATION,
                source="canonical:rrm",
                source_identity="RegistryResourceManager",
                observed_at=ts,
                binding_identity=binding,
                _trusted=True,
            ))

        if resource.has_active_account:
            evidence_list.append(ResourceActivationEvidence(
                evidence_id=f"ev-{uuid4().hex[:12]}",
                resource_id=resource_id,
                resource_kind=resource_kind,
                evidence_type=ActivationEvidenceType.PROVIDER_ACCOUNT,
                source="canonical:rrm",
                source_identity="RegistryResourceManager",
                observed_at=ts,
                _trusted=True,
            ))

        return evidence_list

    def _collect_capability_evidence(
        self, resource, resource_id: str, resource_kind: ResourceDiscoveryKind,
    ) -> list[ResourceActivationEvidence]:
        """Derive capability prerequisite evidence from canonical registry."""
        evidence_list: list[ResourceActivationEvidence] = []
        ts = utc_iso()

        if resource.is_executable:
            binding = ""
            if self._capability_registry is not None:
                for cap_name, registrations in getattr(self._capability_registry, "_registrations", {}).items():
                    for reg in registrations:
                        if getattr(reg, "capability_name", "") == resource.name or getattr(reg, "capability_id", "") == resource_id:
                            binding = getattr(reg, "binding_identity", f"registry:{cap_name}")
                            break
                    if binding:
                        break

            evidence_list.append(ResourceActivationEvidence(
                evidence_id=f"ev-{uuid4().hex[:12]}",
                resource_id=resource_id,
                resource_kind=resource_kind,
                evidence_type=ActivationEvidenceType.CAPABILITY_EXECUTABLE,
                source="canonical:registry",
                source_identity="CanonicalCapabilityRegistry",
                observed_at=ts,
                binding_identity=binding,
                _trusted=True,
            ))

        return evidence_list

    def _collect_agent_evidence(
        self, resource, resource_id: str, resource_kind: ResourceDiscoveryKind,
    ) -> list[ResourceActivationEvidence]:
        """Derive agent prerequisite evidence from canonical registry."""
        from intent_kernel.rrm.models import AgentInstallationState

        evidence_list: list[ResourceActivationEvidence] = []
        ts = utc_iso()

        valid_states = (
            AgentInstallationState.INSTALLED,
            AgentInstallationState.ENABLED,
            AgentInstallationState.AVAILABLE,
        )
        if resource.is_enabled and resource.installation_state in valid_states:
            evidence_list.append(ResourceActivationEvidence(
                evidence_id=f"ev-{uuid4().hex[:12]}",
                resource_id=resource_id,
                resource_kind=resource_kind,
                evidence_type=ActivationEvidenceType.AGENT_IDENTITY,
                source="canonical:rrm",
                source_identity="RegistryResourceManager",
                observed_at=ts,
                _trusted=True,
            ))

        return evidence_list

    def _collect_environment_evidence(
        self, resource, resource_id: str, resource_kind: ResourceDiscoveryKind,
    ) -> list[ResourceActivationEvidence]:
        """Derive environment prerequisite evidence from canonical source."""
        evidence_list: list[ResourceActivationEvidence] = []
        ts = utc_iso()

        if resource.is_discovered:
            evidence_list.append(ResourceActivationEvidence(
                evidence_id=f"ev-{uuid4().hex[:12]}",
                resource_id=resource_id,
                resource_kind=resource_kind,
                evidence_type=ActivationEvidenceType.ENVIRONMENT_DISCOVERY,
                source="canonical:rrm",
                source_identity="RegistryResourceManager",
                observed_at=ts,
                _trusted=True,
            ))

        return evidence_list

    def _collect_account_evidence(
        self, resource, resource_id: str, resource_kind: ResourceDiscoveryKind,
    ) -> list[ResourceActivationEvidence]:
        """Derive account prerequisite evidence from canonical source."""
        evidence_list: list[ResourceActivationEvidence] = []
        ts = utc_iso()

        if resource.secret_reference:
            evidence_list.append(ResourceActivationEvidence(
                evidence_id=f"ev-{uuid4().hex[:12]}",
                resource_id=resource_id,
                resource_kind=resource_kind,
                evidence_type=ActivationEvidenceType.ACCOUNT_SECRET,
                source="canonical:rrm",
                source_identity="RegistryResourceManager",
                observed_at=ts,
                _trusted=True,
            ))

        return evidence_list

    # ------------------------------------------------------------------
    # Validation helpers (for backward-compatible validate_and_store)
    # ------------------------------------------------------------------

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
