"""Movement 18 — Governed Resource Activation Service.

Orchestrates the full governed activation pipeline:

  REGISTERED RESOURCE
  + CANONICAL PREREQUISITE EVIDENCE (validated against canonical sources)
  → ACTIVATION REQUEST
  → PREREQUISITE EVALUATION WITH EVIDENCE
  → TYPED DECISION
  → TOCTOU REVALIDATION
  → ACTIVATION APPLICATION
  → ACTIVATED RESOURCE

No stage may impersonate another.
ACTIVATION APPROVAL IS NOT PREREQUISITE EVIDENCE.
CALLER ASSERTION != CANONICAL SOURCE OF TRUTH.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from intent_kernel.activation.application_boundary import ActivationApplicationBoundary
from intent_kernel.activation.authority import CanonicalResourceActivationAuthority
from intent_kernel.activation.evidence_authority import (
    CanonicalActivationEvidenceAuthority,
    EvidenceValidationResult,
)
from intent_kernel.activation.models import (
    ResourceActivationDecisionType,
    ResourceActivationEvidence,
    ResourceActivationRequest,
    ResourceActivationResult,
    ResourceActivationStatus,
)
from intent_kernel.discovery.models import ResourceDiscoveryKind
from intent_kernel.rrm.service import RegistryResourceManager


class CanonicalResourceActivationService:
    """Orchestrates the governed activation pipeline.

    ORCHESTRATION_ONLY — delegates to sub-services; contains no
    independent mutation logic.
    """

    def __init__(
        self,
        rrm: RegistryResourceManager,
        provider_manager: Any = None,
        capability_registry: Any = None,
    ) -> None:
        self._rrm = rrm
        self._requests: dict[str, ResourceActivationRequest] = {}
        self._decisions: dict[str, object] = {}
        self._consumed_decisions: set[str] = set()
        self._evidence_store: dict[str, ResourceActivationEvidence] = {}
        self._evidence_authority = CanonicalActivationEvidenceAuthority(
            rrm, provider_manager, capability_registry,
        )
        self._authority = CanonicalResourceActivationAuthority(rrm)
        self._application_boundary = ActivationApplicationBoundary(
            rrm, self._requests, self._decisions, self._consumed_decisions,
            self._evidence_store, self._evidence_authority,
        )

    # ------------------------------------------------------------------
    # Sub-service accessors (read-only)
    # ------------------------------------------------------------------

    @property
    def authority(self) -> CanonicalResourceActivationAuthority:
        return self._authority

    @property
    def application_boundary(self) -> ActivationApplicationBoundary:
        return self._application_boundary

    @property
    def evidence_authority(self) -> CanonicalActivationEvidenceAuthority:
        return self._evidence_authority

    @property
    def requests(self) -> dict[str, ResourceActivationRequest]:
        return dict(self._requests)

    @property
    def decisions(self) -> dict[str, object]:
        return dict(self._decisions)

    @property
    def consumed_decisions(self) -> frozenset[str]:
        return frozenset(self._consumed_decisions)

    @property
    def evidence_store(self) -> dict[str, ResourceActivationEvidence]:
        return dict(self._evidence_store)

    # ------------------------------------------------------------------
    # Evidence management — derive from canonical sources only
    # ------------------------------------------------------------------

    def collect_and_register_evidence(
        self,
        resource_id: str,
        resource_kind: ResourceDiscoveryKind,
    ) -> list[ResourceActivationEvidence]:
        """Derive ALL valid prerequisite evidence from canonical sources.

        This is the ONLY trusted entry point. Callers do NOT construct
        evidence objects — the authority derives them by querying the
        canonical source directly.
        """
        evidence_list = self._evidence_authority.collect_for_resource(resource_id, resource_kind)
        for evidence in evidence_list:
            self._evidence_store[evidence.evidence_id] = evidence
            self._authority.register_evidence(evidence)
            self._application_boundary.update_evidence(evidence)
        return evidence_list

    def register_evidence(
        self,
        evidence: ResourceActivationEvidence,
    ) -> EvidenceValidationResult:
        """Register prerequisite evidence for activation evaluation.

        DEPRECATED: use collect_and_register_evidence() instead.
        Evidence is validated against canonical sources before storage.
        Evidence from this path is NOT trusted — only collect_for_resource()
        produces trusted evidence.

        CALLER ASSERTION != CANONICAL SOURCE OF TRUTH.
        """
        validation = self._evidence_authority.validate_and_store(evidence)
        if validation.valid:
            self._evidence_store[evidence.evidence_id] = evidence
            self._authority.register_evidence(evidence)
            self._application_boundary.update_evidence(evidence)
        return validation

    def get_evidence(self, evidence_id: str) -> ResourceActivationEvidence | None:
        return self._evidence_store.get(evidence_id)

    # ------------------------------------------------------------------
    # Convenience entry points
    # ------------------------------------------------------------------

    def create_request(
        self,
        resource_id: str,
        resource_kind: ResourceDiscoveryKind,
        discovery_id: str,
        registration_id: str,
        *,
        scope: str = "global",
        evidence_ids: tuple[str, ...] = (),
        metadata: dict[str, object] | None = None,
    ) -> ResourceActivationRequest:
        """Create an activation request for a registered resource."""
        request = ResourceActivationRequest(
            request_id=f"actreq-{uuid4().hex[:12]}",
            resource_id=resource_id,
            resource_kind=resource_kind,
            discovery_id=discovery_id,
            registration_id=registration_id,
            scope=scope,
            evidence_ids=evidence_ids,
            metadata=metadata or {},
        )
        self._requests[request.request_id] = request
        return request

    def evaluate(
        self,
        request_id: str,
    ):
        """Evaluate activation prerequisites for a request using evidence."""
        request = self._requests.get(request_id)
        if request is None:
            raise ActivationError(f"Request {request_id} not found")
        decision = self._authority.evaluate(request)
        self._decisions[decision.decision_id] = decision
        return decision

    def activate(
        self,
        request_id: str,
        *,
        fresh: bool = True,
    ) -> ResourceActivationResult:
        """Full activation: evaluate + apply decision to RRM."""
        decision = self.evaluate(request_id)
        return self._application_boundary.apply(decision.decision_id)


class ActivationError(Exception):
    """Raised when activation pipeline encounters an unrecoverable error."""
