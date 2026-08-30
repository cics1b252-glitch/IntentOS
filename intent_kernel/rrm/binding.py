"""Canonical RRM-constrained execution-binding selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from intent_kernel.rrm.generation import LEGACY_UNVERSIONED, GENERATION_INITIAL, is_valid_generation


class PreconditionKind(str, Enum):
    """Kind of execution precondition."""
    EXISTING_RESOURCE = "existing_resource"
    EXPECTED_ABSENCE = "expected_absence"


@dataclass(frozen=True, slots=True)
class ExecutionPrecondition:
    """Immutable canonical execution precondition contract.

    Represents a resource precondition such as:
    - Existing resource must match governed_registration_id and generation
    - Expected absence for CREATE operations

    Does NOT contain executable objects, verification status, authority tokens,
    or mutable RRM references. Immutable and deterministic.
    """

    kind: PreconditionKind
    resource_id: str
    governed_registration_id: str = ""
    expected_generation: int = 0

    def __post_init__(self) -> None:
        # Fail closed on malformed preconditions at construction time
        if not self.resource_id:
            raise ValueError("ExecutionPrecondition.resource_id must not be empty")
        if self.kind is PreconditionKind.EXISTING_RESOURCE:
            if not self.governed_registration_id:
                raise ValueError("EXISTING_RESOURCE precondition requires governed_registration_id")
            if not is_valid_generation(self.expected_generation):
                raise ValueError(
                    f"EXISTING_RESOURCE precondition requires valid expected_generation (>= {GENERATION_INITIAL}), got {self.expected_generation}"
                )
        elif self.kind is PreconditionKind.EXPECTED_ABSENCE:
            # Absence is represented explicitly, not as generation 0
            if self.governed_registration_id:
                raise ValueError("EXPECTED_ABSENCE precondition must not have governed_registration_id")
            if self.expected_generation != 0:
                raise ValueError("EXPECTED_ABSENCE precondition must have expected_generation = 0")
        else:
            raise ValueError(f"Unknown precondition kind: {self.kind}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "resource_id": self.resource_id,
            "governed_registration_id": self.governed_registration_id,
            "expected_generation": self.expected_generation,
        }


@dataclass(frozen=True, slots=True)
class ResourceBindingDecision:
    capability: str
    registration: Any | None  # CapabilityRegistration | None (avoid forward ref issues)
    available: bool
    reason: str
    registered: bool = False
    rrm_eligible: bool = False
    binding_healthy: bool = False
    selected_binding: str | None = None
    authority: str = "RRM"
    binding_identity: str = ""
    execution_preconditions: tuple[ExecutionPrecondition, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "available": self.available,
            "reason": self.reason,
            "registered": self.registered,
            "rrm_eligible": self.rrm_eligible,
            "binding_healthy": self.binding_healthy,
            "selected_binding": self.selected_binding,
            "authority": self.authority,
            "binding_identity": self.binding_identity,
            "execution_preconditions": [pc.to_dict() for pc in self.execution_preconditions],
        }


@dataclass(frozen=True, slots=True)
class ResourceBindingRevalidation:
    capability: str
    valid: bool
    binding_registered: bool
    rrm_eligible: bool
    binding_healthy: bool
    reason: str
    authority: str = "RRM"
    binding_identity: str = ""
    execution_preconditions: tuple[ExecutionPrecondition, ...] = ()

    def __bool__(self) -> bool:
        return self.valid

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "valid": self.valid,
            "binding_registered": self.binding_registered,
            "rrm_eligible": self.rrm_eligible,
            "binding_healthy": self.binding_healthy,
            "reason": self.reason,
            "authority": self.authority,
            "binding_identity": self.binding_identity,
            "execution_preconditions": [pc.to_dict() for pc in self.execution_preconditions],
        }


class CanonicalResourceBindingAuthority:
    """Select invocation bindings only when canonical RRM truth permits them."""

    def __init__(self, rrm, registry) -> None:
        self.rrm = rrm
        self.registry = registry
        self.last_resolution: ResourceBindingDecision | None = None
        self.last_revalidation: ResourceBindingRevalidation | None = None

    async def resolve(
        self, capability: str, *, preferred_kind: Any | None = None
    ) -> ResourceBindingDecision:
        # Lazy import to avoid circular import
        from intent_kernel.orchestration.registry import ExecutorKind

        entries = sorted(
            self.registry.discover(capability, executor_kind=preferred_kind),
            key=lambda item: (item.executor_kind.value, item.executor_id),
        )
        if not entries:
            decision = ResourceBindingDecision(
                capability, None, False, "binding_missing"
            )
            self.last_resolution = decision
            return decision
        eligible = [entry for entry in entries if self._rrm_eligible(entry)]
        for entry in eligible:
            if not await self.registry.available(entry):
                continue
            preconditions = self._build_execution_preconditions(entry)
            decision = ResourceBindingDecision(
                capability=capability,
                registration=entry,
                available=True,
                reason="eligible_binding",
                registered=True,
                rrm_eligible=True,
                binding_healthy=True,
                selected_binding=f"{entry.executor_kind.value}:{entry.executor_id}",
                binding_identity=entry.binding_identity,
                execution_preconditions=tuple(preconditions),
            )
            self.last_resolution = decision
            return decision
        decision = ResourceBindingDecision(
            capability=capability,
            registration=None,
            available=False,
            reason=(
                "binding_unhealthy" if eligible else "rrm_rejected_bindings"
            ),
            registered=True,
            rrm_eligible=bool(eligible),
            binding_healthy=False,
        )
        self.last_resolution = decision
        return decision

    async def revalidate(
        self, decision: ResourceBindingDecision
    ) -> ResourceBindingRevalidation:
        registration = decision.registration
        binding_registered = bool(
            registration is not None and self.registry.contains(registration)
        )
        rrm_eligible = bool(
            registration is not None
            and binding_registered
            and self._rrm_eligible(registration)
        )
        binding_healthy = bool(
            registration is not None
            and rrm_eligible
            and await self.registry.available(registration)
        )
        valid = bool(
            decision.available
            and registration is not None
            and binding_registered
            and rrm_eligible
            and binding_healthy
        )
        if not binding_registered:
            reason = "binding_disappeared"
        elif not rrm_eligible:
            reason = "rrm_rejected_at_dispatch"
        elif not binding_healthy:
            reason = "binding_unhealthy_at_dispatch"
        else:
            reason = "dispatch_revalidated"
        result = ResourceBindingRevalidation(
            capability=decision.capability,
            valid=valid,
            binding_registered=binding_registered,
            rrm_eligible=rrm_eligible,
            binding_healthy=binding_healthy,
            reason=reason,
            binding_identity=(
                registration.binding_identity
                if registration is not None
                else decision.binding_identity
            ),
            execution_preconditions=decision.execution_preconditions,
        )
        self.last_revalidation = result
        return result

    def _build_execution_preconditions(self, entry: CapabilityRegistration) -> list[ExecutionPrecondition]:
        """Build execution preconditions for the given binding entry.

        Derives preconditions from the canonical RRM resources that the binding
        involves. For provider bindings, this includes the provider resource's
        governed_registration_id and generation. For agent bindings, the agent
        resource. For core apps, the capability resource.
        """
        # Lazy import to avoid circular import
        from intent_kernel.orchestration.registry import ExecutorKind

        preconditions: list[ExecutionPrecondition] = []

        if entry.executor_kind is ExecutorKind.PROVIDER:
            provider = self.rrm.get_provider(entry.executor_id)
            if provider is not None and is_valid_generation(getattr(provider, "generation", 0)):
                preconditions.append(
                    ExecutionPrecondition(
                        kind=PreconditionKind.EXISTING_RESOURCE,
                        resource_id=entry.executor_id,
                        governed_registration_id=provider.governed_registration_id or "",
                        expected_generation=provider.generation,
                    )
                )
        elif entry.executor_kind is ExecutorKind.AGENT:
            agent = self.rrm.get_agent(entry.executor_id)
            if agent is not None and is_valid_generation(getattr(agent, "generation", 0)):
                preconditions.append(
                    ExecutionPrecondition(
                        kind=PreconditionKind.EXISTING_RESOURCE,
                        resource_id=entry.executor_id,
                        governed_registration_id=agent.governed_registration_id or "",
                        expected_generation=agent.generation,
                    )
                )
        elif entry.executor_kind is ExecutorKind.CORE_APP:
            capability_resource = self.rrm.get_capability(entry.capability.name)
            if capability_resource is not None and is_valid_generation(getattr(capability_resource, "generation", 0)):
                preconditions.append(
                    ExecutionPrecondition(
                        kind=PreconditionKind.EXISTING_RESOURCE,
                        resource_id=entry.capability.name,
                        governed_registration_id=capability_resource.governed_registration_id or "",
                        expected_generation=capability_resource.generation,
                    )
                )

        return preconditions

    def _rrm_eligible(self, entry: Any) -> bool:
        # Lazy import to avoid circular import
        from intent_kernel.orchestration.registry import ExecutorKind

        if entry.executor_kind is ExecutorKind.CORE_APP:
            resource = self.rrm.get_capability(entry.capability.name)
            return bool(
                resource and resource.is_eligible
                and resource.metadata.get("executor_kind") == "core_app"
                and resource.metadata.get("executor_id") == entry.executor_id
            )
        if entry.executor_kind is ExecutorKind.AGENT:
            resource = self.rrm.get_agent(entry.executor_id)
            return bool(resource and resource.is_eligible and entry.capability.name in resource.capabilities)
        if entry.executor_kind is ExecutorKind.PROVIDER:
            resource = self.rrm.get_provider(entry.executor_id)
            capabilities = resource.metadata.get("capabilities", []) if resource else []
            provider_capability = entry.capability.name.removeprefix("provider.")
            return bool(resource and resource.is_eligible and provider_capability in capabilities)
        return False
