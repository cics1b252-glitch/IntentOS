"""Movement 18 — Governed Resource Activation Service.

Orchestrates the full governed activation pipeline:

  REGISTERED RESOURCE
  → ACTIVATION REQUEST
  → PREREQUISITE EVALUATION
  → TYPED DECISION
  → TOCTOU REVALIDATION
  → ACTIVATION APPLICATION
  → ACTIVATED RESOURCE

No stage may impersonate another.
"""

from __future__ import annotations

from uuid import uuid4

from intent_kernel.activation.application_boundary import ActivationApplicationBoundary
from intent_kernel.activation.authority import CanonicalResourceActivationAuthority
from intent_kernel.activation.models import (
    ResourceActivationDecisionType,
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

    def __init__(self, rrm: RegistryResourceManager) -> None:
        self._rrm = rrm
        self._requests: dict[str, ResourceActivationRequest] = {}
        self._decisions: dict[str, object] = {}
        self._consumed_decisions: set[str] = set()
        self._authority = CanonicalResourceActivationAuthority(rrm)
        self._application_boundary = ActivationApplicationBoundary(
            rrm, self._requests, self._decisions, self._consumed_decisions,  # type: ignore[arg-type]
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
    def requests(self) -> dict[str, ResourceActivationRequest]:
        return dict(self._requests)

    @property
    def decisions(self) -> dict[str, object]:
        return dict(self._decisions)

    @property
    def consumed_decisions(self) -> frozenset[str]:
        return frozenset(self._consumed_decisions)

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
            metadata=metadata or {},
        )
        self._requests[request.request_id] = request
        return request

    def evaluate(
        self,
        request_id: str,
    ):
        """Evaluate activation prerequisites for a request."""
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
