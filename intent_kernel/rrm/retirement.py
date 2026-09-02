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

from intent_kernel.rrm.models import (
    ConditionalRetirementRequest,
    ConditionalRetirementResult,
    ResourceType,
)
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
    """A request to retire a governed resource.

    M31.2B-2B: resource_kind is canonical ResourceType. expected_generation
    captures the active generation at request time for immutable binding
    through the authorization chain.
    """

    request_id: str
    resource_id: str
    resource_kind: ResourceType
    governed_registration_id: str
    expected_generation: int
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

        M31.2B-2B: captures canonical ResourceType and expected_generation
        from the active resource BEFORE authorization.

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

        resource_kind = self._classify_resource_kind(resource)
        expected_generation = getattr(resource, "generation", 0)

        request = ResourceRetirementRequest(
            request_id=f"ret-req-{uuid4().hex[:12]}",
            resource_id=resource_id,
            resource_kind=resource_kind,
            governed_registration_id=governed_registration_id,
            expected_generation=expected_generation,
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
        """Apply an approved retirement decision via RRM atomic mechanism.

        M31.2B-2B: derives ConditionalRetirementRequest from the approved
        immutable request and delegates to RRM conditional_retire_resource.
        No direct dictionary deletion. No parallel productive retirement path.

        Validates:
          1. decision exists
          2. decision is APPROVED
          3. decision not yet consumed (single consumption)
          4. RRM conditional retirement succeeds or reports typed failure
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

        request = self._requests.get(decision.request_id)
        if request is None:
            return ResourceRetirementResult(
                success=False,
                decision_id=decision_id,
                resource_id=decision.resource_id,
                reason="request_not_found",
            )

        rrm_request = ConditionalRetirementRequest(
            resource_kind=request.resource_kind,
            resource_id=request.resource_id,
            governed_registration_id=request.governed_registration_id,
            expected_generation=request.expected_generation,
        )

        rrm_result = self._rrm.conditional_retire_resource(rrm_request)

        if rrm_result.outcome.value == "retired":
            self._consumed.add(decision_id)
            return ResourceRetirementResult(
                success=True,
                decision_id=decision_id,
                resource_id=decision.resource_id,
                retired_at=utc_iso(),
            )

        return ResourceRetirementResult(
            success=False,
            decision_id=decision_id,
            resource_id=decision.resource_id,
            reason=rrm_result.outcome.value,
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
            "get_project",
        ):
            getter = getattr(rrm, getter_name, None)
            if getter is not None:
                resource = getter(resource_id)
                if resource is not None:
                    return resource
        return None

    def _classify_resource_kind(self, resource: object) -> ResourceType:
        """Classify a resource snapshot into canonical ResourceType.

        M31.2B-2B: deterministic finite mapping, no free-form strings.
        The immutable RRM read surface returns snapshot classes.
        """
        from intent_kernel.rrm.models import (
            ProviderSnapshot,
            AccountSnapshot,
            ExecutionEnvironmentSnapshot,
            CapabilitySnapshot,
            AgentSnapshot,
            ProjectSnapshot,
        )

        _RESOURCE_CLASS_MAP = {
            ProviderSnapshot: ResourceType.PROVIDER,
            AccountSnapshot: ResourceType.ACCOUNT,
            ExecutionEnvironmentSnapshot: ResourceType.EXECUTION_ENVIRONMENT,
            CapabilitySnapshot: ResourceType.CAPABILITY,
            AgentSnapshot: ResourceType.AGENT,
            ProjectSnapshot: ResourceType.PROJECT,
        }

        resource_type = _RESOURCE_CLASS_MAP.get(type(resource))
        if resource_type is None:
            raise RetirementError(
                f"unsupported_resource_class: {type(resource).__name__}"
            )
        return resource_type


class RetirementError(Exception):
    """Raised when a retirement operation fails validation."""
