"""Movement 18 — Canonical Activation Authority.

ACTIVATION_ONLY — evaluates whether a registered resource satisfies
activation prerequisites using INDEPENDENT EVIDENCE.

ACTIVATION MUST VERIFY PREREQUISITE TRUTH.
ACTIVATION MUST NOT INVENT PREREQUISITE TRUTH.
ACTIVATION APPROVAL IS NOT PREREQUISITE EVIDENCE.

It MAY:
  - inspect exact registered resource
  - inspect independent prerequisite evidence
  - evaluate activation prerequisites against evidence
  - approve or reject activation

It MUST NOT:
  - execute
  - authorize
  - select provider
  - select Core App
  - dispatch
  - create Mission
  - confirm Mission
  - verify
  - complete Mission
  - write memory
  - manufacture discovery evidence
  - manufacture promotion approval
  - directly mutate RRM
  - manufacture prerequisite truth
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from intent_kernel.activation.models import (
    ActivationEvidenceType,
    ResourceActivationDecision,
    ResourceActivationDecisionType,
    ResourceActivationEvidence,
    ResourceActivationRequest,
    ResourceActivationStatus,
)
from intent_kernel.discovery.models import ResourceDiscoveryKind
from intent_kernel.rrm.models import ResourceType
from intent_kernel.rrm.service import RegistryResourceManager
from intent_kernel.time_utils import utc_iso


# ---------------------------------------------------------------------------
# Resource-kind prerequisite evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PrerequisiteResult:
    """Result of evaluating a single activation prerequisite."""

    name: str
    satisfied: bool
    detail: str = ""


# Privileged roles that must not alter activation result
_PRIVILEGED_ROLES: frozenset[str] = frozenset({
    "admin", "root", "system", "trusted", "supervisor",
})


class CanonicalResourceActivationAuthority:
    """ACTIVATION_ONLY — evaluates activation prerequisites using evidence.

    This authority inspects the registered resource AND independent
    prerequisite evidence to determine whether activation prerequisites
    are satisfied. It produces a typed APPROVE/REJECT decision but must
    NOT directly mutate RRM.

    ACTIVATION APPROVAL IS NOT PREREQUISITE EVIDENCE.
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

    def __init__(self, rrm: RegistryResourceManager) -> None:
        self._rrm = rrm
        self._evidence_store: dict[str, ResourceActivationEvidence] = {}

    def register_evidence(self, evidence: ResourceActivationEvidence) -> None:
        """Register prerequisite evidence for authority evaluation."""
        self._evidence_store[evidence.evidence_id] = evidence

    def get_evidence(self, evidence_id: str) -> ResourceActivationEvidence | None:
        return self._evidence_store.get(evidence_id)

    def evaluate(
        self,
        request: ResourceActivationRequest,
    ) -> ResourceActivationDecision:
        """Evaluate activation prerequisites using evidence and produce a decision.

        ACTIVATION_ONLY — does NOT mutate RRM.
        """
        resource_type = self._RESOURCE_TYPE_MAP.get(request.resource_kind)
        if resource_type is None:
            return self._reject(request, "unsupported_resource_kind",
                                f"Resource kind {request.resource_kind.value} is not supported for activation")

        resource = self._get_resource(resource_type, request.resource_id)
        if resource is None:
            return self._reject(request, "resource_not_registered",
                                f"Resource {request.resource_id} is not registered in RRM")

        prerequisites = self._evaluate_prerequisites(resource_type, resource, request)

        all_satisfied = all(p.satisfied for p in prerequisites)
        prereq_names = tuple(p.name for p in prerequisites)

        if all_satisfied:
            return ResourceActivationDecision(
                decision_id=f"actdec-{uuid4().hex[:12]}",
                request_id=request.request_id,
                resource_id=request.resource_id,
                resource_kind=request.resource_kind,
                decision_type=ResourceActivationDecisionType.APPROVE,
                reasoning="All activation prerequisites satisfied with independent evidence",
                prerequisites_evaluated=prereq_names,
                evidence_verified=tuple(request.evidence_ids),
                scope=request.scope,
            )
        else:
            failed = [p for p in prerequisites if not p.satisfied]
            detail = "; ".join(f"{p.name}: {p.detail}" for p in failed)
            return self._reject(request, "prerequisites_not_satisfied", detail)

    def _reject(
        self,
        request: ResourceActivationRequest,
        reason: str,
        detail: str,
    ) -> ResourceActivationDecision:
        return ResourceActivationDecision(
            decision_id=f"actdec-{uuid4().hex[:12]}",
            request_id=request.request_id,
            resource_id=request.resource_id,
            resource_kind=request.resource_kind,
            decision_type=ResourceActivationDecisionType.REJECT,
            reasoning=f"{reason}: {detail}",
            prerequisites_evaluated=(),
            evidence_verified=(),
            scope=request.scope,
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

    def _evaluate_prerequisites(
        self,
        resource_type: ResourceType,
        resource,
        request: ResourceActivationRequest,
    ) -> list[_PrerequisiteResult]:
        """Evaluate ALL prerequisites including resource-kind-specific evidence.

        For every APPROVED decision, each prerequisite must have independent
        canonical evidence. The authority does NOT fabricate prerequisite truth.
        """
        results: list[_PrerequisiteResult] = []

        # Structural invariants (always required)
        results.append(_PrerequisiteResult(
            name="resource_registered",
            satisfied=True,
            detail="Resource exists in RRM",
        ))

        results.append(_PrerequisiteResult(
            name="not_template",
            satisfied=not resource.is_template,
            detail="Resource is a template" if resource.is_template else "",
        ))

        results.append(_PrerequisiteResult(
            name="origin_not_template",
            satisfied=resource.resource_origin.value != "template",
            detail="Resource origin is TEMPLATE" if resource.resource_origin.value == "template" else "",
        ))

        results.append(_PrerequisiteResult(
            name="status_active",
            satisfied=resource.status.value == "active",
            detail=f"Resource status is {resource.status.value}" if resource.status.value != "active" else "",
        ))

        # Resource-kind-specific prerequisites validated via evidence
        if resource_type == ResourceType.PROVIDER:
            results.extend(self._evaluate_provider_prerequisites(resource, request))
        elif resource_type == ResourceType.CAPABILITY:
            results.extend(self._evaluate_capability_prerequisites(resource, request))
        elif resource_type == ResourceType.AGENT:
            results.extend(self._evaluate_agent_prerequisites(resource, request))
        elif resource_type == ResourceType.EXECUTION_ENVIRONMENT:
            results.extend(self._evaluate_environment_prerequisites(resource, request))
        elif resource_type == ResourceType.ACCOUNT:
            results.extend(self._evaluate_account_prerequisites(resource, request))

        return results

    def _evaluate_provider_prerequisites(
        self, resource, request: ResourceActivationRequest,
    ) -> list[_PrerequisiteResult]:
        """Provider activation requires independent configuration/account evidence."""
        results: list[_PrerequisiteResult] = []

        config_evidence = self._find_valid_evidence(
            request.evidence_ids, ActivationEvidenceType.PROVIDER_CONFIGURATION,
        )
        if config_evidence is None:
            results.append(_PrerequisiteResult(
                name="provider_configured",
                satisfied=False,
                detail="No independent configuration evidence provided",
            ))
        elif not resource.is_configured:
            results.append(_PrerequisiteResult(
                name="provider_configured",
                satisfied=False,
                detail=f"Evidence {config_evidence.evidence_id} exists but resource is_configured=False",
            ))
        else:
            results.append(_PrerequisiteResult(
                name="provider_configured",
                satisfied=True,
                detail=f"Verified via evidence {config_evidence.evidence_id}",
            ))

        account_evidence = self._find_valid_evidence(
            request.evidence_ids, ActivationEvidenceType.PROVIDER_ACCOUNT,
        )
        if account_evidence is None:
            results.append(_PrerequisiteResult(
                name="provider_has_active_account",
                satisfied=False,
                detail="No independent active-account evidence provided",
            ))
        elif not resource.has_active_account:
            results.append(_PrerequisiteResult(
                name="provider_has_active_account",
                satisfied=False,
                detail=f"Evidence {account_evidence.evidence_id} exists but resource has_active_account=False",
            ))
        else:
            results.append(_PrerequisiteResult(
                name="provider_has_active_account",
                satisfied=True,
                detail=f"Verified via evidence {account_evidence.evidence_id}",
            ))

        return results

    def _evaluate_capability_prerequisites(
        self, resource, request: ResourceActivationRequest,
    ) -> list[_PrerequisiteResult]:
        """Capability activation requires exact executable binding evidence."""
        results: list[_PrerequisiteResult] = []

        exec_evidence = self._find_valid_evidence(
            request.evidence_ids, ActivationEvidenceType.CAPABILITY_EXECUTABLE,
        )
        if exec_evidence is None:
            results.append(_PrerequisiteResult(
                name="capability_executable",
                satisfied=False,
                detail="No independent executable binding evidence provided",
            ))
        elif not resource.is_executable:
            results.append(_PrerequisiteResult(
                name="capability_executable",
                satisfied=False,
                detail=f"Evidence {exec_evidence.evidence_id} exists but resource is_executable=False",
            ))
        else:
            results.append(_PrerequisiteResult(
                name="capability_executable",
                satisfied=True,
                detail=f"Verified via evidence {exec_evidence.evidence_id}",
            ))

        return results

    def _evaluate_agent_prerequisites(
        self, resource, request: ResourceActivationRequest,
    ) -> list[_PrerequisiteResult]:
        """Agent activation requires independent governed identity/state evidence."""
        results: list[_PrerequisiteResult] = []

        agent_evidence = self._find_valid_evidence(
            request.evidence_ids, ActivationEvidenceType.AGENT_IDENTITY,
        )
        if agent_evidence is None:
            results.append(_PrerequisiteResult(
                name="agent_governed_identity",
                satisfied=False,
                detail="No independent governed agent identity evidence provided",
            ))
        else:
            role = str(resource.metadata.get("role", "")).lower()
            if role in _PRIVILEGED_ROLES:
                results.append(_PrerequisiteResult(
                    name="agent_governed_identity",
                    satisfied=False,
                    detail=f"Privileged role '{role}' must not alter activation result",
                ))
            elif not resource.is_enabled:
                results.append(_PrerequisiteResult(
                    name="agent_governed_identity",
                    satisfied=False,
                    detail=f"Evidence {agent_evidence.evidence_id} exists but resource is_enabled=False",
                ))
            else:
                from intent_kernel.rrm.models import AgentInstallationState
                valid_states = (
                    AgentInstallationState.INSTALLED,
                    AgentInstallationState.ENABLED,
                    AgentInstallationState.AVAILABLE,
                )
                if resource.installation_state not in valid_states:
                    results.append(_PrerequisiteResult(
                        name="agent_governed_identity",
                        satisfied=False,
                        detail=(
                            f"Evidence {agent_evidence.evidence_id} exists but "
                            f"installation_state={resource.installation_state.value}"
                        ),
                    ))
                else:
                    results.append(_PrerequisiteResult(
                        name="agent_governed_identity",
                        satisfied=True,
                        detail=f"Verified via evidence {agent_evidence.evidence_id}",
                    ))

        return results

    def _evaluate_environment_prerequisites(
        self, resource, request: ResourceActivationRequest,
    ) -> list[_PrerequisiteResult]:
        """Environment activation requires independent discovery evidence."""
        results: list[_PrerequisiteResult] = []

        disc_evidence = self._find_valid_evidence(
            request.evidence_ids, ActivationEvidenceType.ENVIRONMENT_DISCOVERY,
        )
        if disc_evidence is None:
            results.append(_PrerequisiteResult(
                name="environment_discovered",
                satisfied=False,
                detail="No independent discovery evidence provided",
            ))
        elif not resource.is_discovered:
            results.append(_PrerequisiteResult(
                name="environment_discovered",
                satisfied=False,
                detail=f"Evidence {disc_evidence.evidence_id} exists but resource is_discovered=False",
            ))
        else:
            results.append(_PrerequisiteResult(
                name="environment_discovered",
                satisfied=True,
                detail=f"Verified via evidence {disc_evidence.evidence_id}",
            ))

        return results

    def _evaluate_account_prerequisites(
        self, resource, request: ResourceActivationRequest,
    ) -> list[_PrerequisiteResult]:
        """Account activation requires existing canonical secret/configuration evidence."""
        results: list[_PrerequisiteResult] = []

        secret_evidence = self._find_valid_evidence(
            request.evidence_ids, ActivationEvidenceType.ACCOUNT_SECRET,
        )
        if secret_evidence is None:
            results.append(_PrerequisiteResult(
                name="account_secret_reference",
                satisfied=False,
                detail="No independent secret-reference evidence provided",
            ))
        elif not resource.secret_reference:
            results.append(_PrerequisiteResult(
                name="account_secret_reference",
                satisfied=False,
                detail=f"Evidence {secret_evidence.evidence_id} exists but resource secret_reference is empty",
            ))
        else:
            results.append(_PrerequisiteResult(
                name="account_secret_reference",
                satisfied=True,
                detail=f"Verified via evidence {secret_evidence.evidence_id}",
            ))

        return results

    def _find_valid_evidence(
        self,
        evidence_ids: tuple[str, ...],
        evidence_type: ActivationEvidenceType,
    ) -> ResourceActivationEvidence | None:
        """Find valid (non-revoked) evidence of the required type."""
        for eid in evidence_ids:
            evidence = self._evidence_store.get(eid)
            if evidence is None:
                continue
            if evidence.revoked:
                continue
            if evidence.evidence_type != evidence_type:
                continue
            return evidence
        return None
