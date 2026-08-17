"""Movement 18 — Canonical Activation Authority.

ACTIVATION_ONLY — evaluates whether a registered resource satisfies
activation prerequisites and produces a typed decision.

It MAY:
  - inspect exact registered resource
  - inspect configuration state
  - inspect binding requirements
  - inspect supported resource kind
  - evaluate activation prerequisites
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
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from intent_kernel.activation.models import (
    ResourceActivationDecision,
    ResourceActivationDecisionType,
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


class CanonicalResourceActivationAuthority:
    """ACTIVATION_ONLY — evaluates activation prerequisites.

    This authority inspects the registered resource and its configuration
    to determine whether activation prerequisites are satisfied. It produces
    a typed APPROVE/REJECT decision but must NOT directly mutate RRM.
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

    def evaluate(
        self,
        request: ResourceActivationRequest,
    ) -> ResourceActivationDecision:
        """Evaluate activation prerequisites and produce a decision.

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
                reasoning="All activation prerequisites satisfied",
                prerequisites_evaluated=prereq_names,
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
        """Evaluate structural invariants only.

        Authority approves based on: registered, not template, active status.
        Resource-kind-specific prerequisites (is_configured, has_active_account,
        is_executable, is_enabled, installation_state, is_discovered,
        secret_reference) are NOT checked because they are the fields that
        activation itself establishes.
        """
        results: list[_PrerequisiteResult] = []

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

        return results
