"""Movement 19 — Governed Resource Retirement Authority.

RETIREMENT_ONLY — canonical authority for intentional removal of governed
resources from the RRM.

GENERIC UNREGISTER cannot remove governed resources.
CANONICAL RETIREMENT is the only authorized removal path.

The authority owns retirement request/decision.
A narrow application boundary owns the actual authorized removal.

RETIREMENT_ONLY — must NOT become:
  - registration authority
  - activation authority
  - binding authority
  - authorization authority
  - execution authority
  - verification authority
  - completion authority
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from intent_kernel.time_utils import utc_iso


class ResourceRetirementDecisionType(str, Enum):
    """Typed decision for retirement requests."""

    APPROVE = "approve"
    DENY = "deny"


class ResourceRetirementStateType(str, Enum):
    """Lifecycle state for a retirement request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    CONSUMED = "consumed"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class ResourceRetirementRequest:
    """A request to retire a governed resource."""

    request_id: str
    resource_id: str
    resource_kind: str
    governed_registration_id: str
    reason: str
    created_at: str = field(default_factory=utc_iso)


@dataclass(frozen=True, slots=True)
class ResourceRetirementDecision:
    """A decision on a retirement request."""

    decision_id: str
    request_id: str
    resource_id: str
    governed_registration_id: str
    decision_type: ResourceRetirementDecisionType
    reason: str
    created_at: str = field(default_factory=utc_iso)
    _authority_token: object = field(default_factory=lambda: _RETIREMENT_AUTHORITY_TOKEN, repr=False)


_RETIREMENT_AUTHORITY_TOKEN = object()


@dataclass(frozen=True, slots=True)
class ResourceRetirementResult:
    """Result of applying a retirement decision."""

    success: bool
    decision_id: str
    resource_id: str
    retired_at: str = ""
    reason: str = ""


class CanonicalResourceRetirementAuthority:
    """RETIREMENT_ONLY — decides whether a governed resource may be retired.

    Ownership:
      - retirement request creation
      - retirement decision (APPROVE / DENY)
      - exact identity validation (resource_id + governed_registration_id)
      - single consumption enforcement

    The authority does NOT:
      - register resources
      - activate resources
      - bind resources
      - authorize execution
      - execute
      - verify
      - complete Missions
    """

    def __init__(self, rrm: object) -> None:
        self._rrm = rrm
        self._requests: dict[str, ResourceRetirementRequest] = {}
        self._decisions: dict[str, ResourceRetirementDecision] = {}
        self._consumed: set[str] = set()

    def request_retirement(
        self,
        resource_id: str,
        governed_registration_id: str,
        reason: str = "",
    ) -> ResourceRetirementRequest:
        """Create a retirement request for a governed resource.

        Validates:
          1. resource exists in RRM
          2. resource is governed
          3. governed_registration_id matches
        """
        resource = self._get_resource(resource_id)
        if resource is None:
            raise RetirementError(f"resource_not_found: {resource_id}")

        actual_grid = getattr(resource, "governed_registration_id", "")
        if not actual_grid:
            raise RetirementError(f"resource_not_governed: {resource_id}")
        if actual_grid != governed_registration_id:
            raise RetirementError("governed_registration_id_mismatch")

        request = ResourceRetirementRequest(
            request_id=f"ret-req-{uuid4().hex[:12]}",
            resource_id=resource_id,
            resource_kind=type(resource).__name__,
            governed_registration_id=governed_registration_id,
            reason=reason,
        )
        self._requests[request.request_id] = request
        return request

    def decide_retirement(
        self,
        request_id: str,
        *,
        approved: bool,
        reason: str = "",
    ) -> ResourceRetirementDecision:
        """Decide on a retirement request.

        Validates:
          1. request exists
          2. request is still pending (not already decided)
          3. resource still has matching governed_registration_id
        """
        request = self._requests.get(request_id)
        if request is None:
            raise RetirementError(f"request_not_found: {request_id}")

        resource = self._get_resource(request.resource_id)
        if resource is None:
            raise RetirementError(f"resource_not_found: {request.resource_id}")

        actual_grid = getattr(resource, "governed_registration_id", "")
        if actual_grid != request.governed_registration_id:
            raise RetirementError("governed_registration_id_mismatch")

        decision = ResourceRetirementDecision(
            decision_id=f"ret-dec-{uuid4().hex[:12]}",
            request_id=request_id,
            resource_id=request.resource_id,
            governed_registration_id=request.governed_registration_id,
            decision_type=(
                ResourceRetirementDecisionType.APPROVE
                if approved
                else ResourceRetirementDecisionType.DENY
            ),
            reason=reason,
        )
        self._decisions[decision.decision_id] = decision
        return decision

    def apply_retirement(self, decision_id: str) -> ResourceRetirementResult:
        """Apply an approved retirement decision to remove the resource.

        Validates:
          1. decision exists
          2. decision is APPROVED
          3. decision not yet consumed (single consumption)
          4. resource still exists with matching governed_registration_id
          5. Performs actual removal from RRM

        Returns ResourceRetirementResult.
        """
        decision = self._decisions.get(decision_id)
        if decision is None:
            return ResourceRetirementResult(
                success=False,
                decision_id=decision_id,
                resource_id="",
                reason="decision_not_found",
            )

        if decision.decision_type != ResourceRetirementDecisionType.APPROVE:
            return ResourceRetirementResult(
                success=False,
                decision_id=decision_id,
                resource_id=decision.resource_id,
                reason="decision_not_approved",
            )

        if decision_id in self._consumed:
            return ResourceRetirementResult(
                success=False,
                decision_id=decision_id,
                resource_id=decision.resource_id,
                reason="decision_already_consumed",
            )

        resource = self._get_resource(decision.resource_id)
        if resource is None:
            return ResourceRetirementResult(
                success=False,
                decision_id=decision_id,
                resource_id=decision.resource_id,
                reason="resource_not_found",
            )

        actual_grid = getattr(resource, "governed_registration_id", "")
        if actual_grid != decision.governed_registration_id:
            return ResourceRetirementResult(
                success=False,
                decision_id=decision_id,
                resource_id=decision.resource_id,
                reason="governed_registration_id_mismatch",
            )

        removed = self._remove_resource(decision.resource_id)
        if not removed:
            return ResourceRetirementResult(
                success=False,
                decision_id=decision_id,
                resource_id=decision.resource_id,
                reason="removal_failed",
            )

        self._consumed.add(decision_id)
        return ResourceRetirementResult(
            success=True,
            decision_id=decision_id,
            resource_id=decision.resource_id,
            retired_at=utc_iso(),
        )

    def get_request(self, request_id: str) -> ResourceRetirementRequest | None:
        return self._requests.get(request_id)

    def get_decision(self, decision_id: str) -> ResourceRetirementDecision | None:
        return self._decisions.get(decision_id)

    def is_decision_consumed(self, decision_id: str) -> bool:
        return decision_id in self._consumed

    def _get_resource(self, resource_id: str) -> object | None:
        rrm = self._rrm
        for getter_name in (
            "get_provider",
            "get_capability",
            "get_agent",
            "get_environment",
            "get_account",
        ):
            getter = getattr(rrm, getter_name, None)
            if getter is not None:
                resource = getter(resource_id)
                if resource is not None:
                    return resource
        return None

    def _remove_resource(self, resource_id: str) -> bool:
        """Remove governed resource directly from RRM internal state.

        Bypasses guarded unregister_*() which rejects governed resources.
        This is the ONLY authorized removal path for governed resources.
        """
        rrm = self._rrm
        with rrm._lock:
            if resource_id in rrm._providers:
                del rrm._providers[resource_id]
                return True
            if resource_id in rrm._accounts:
                del rrm._accounts[resource_id]
                return True
            if resource_id in rrm._environments:
                del rrm._environments[resource_id]
                return True
            if resource_id in rrm._agents:
                del rrm._agents[resource_id]
                return True
            if resource_id in rrm._capabilities:
                keys_to_del = [k for k, v in rrm._capabilities.items() if k == resource_id or getattr(v, "resource_id", None) == resource_id]
                for k in keys_to_del:
                    del rrm._capabilities[k]
                if keys_to_del:
                    return True
        return False


class RetirementError(Exception):
    """Raised when a retirement operation fails validation."""
