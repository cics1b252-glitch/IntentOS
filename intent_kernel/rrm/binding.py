"""Canonical RRM-constrained execution-binding selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from intent_kernel.orchestration.registry import CapabilityRegistration, ExecutorKind


@dataclass(frozen=True, slots=True)
class ResourceBindingDecision:
    capability: str
    registration: CapabilityRegistration | None
    available: bool
    reason: str
    registered: bool = False
    rrm_eligible: bool = False
    binding_healthy: bool = False
    selected_binding: str | None = None
    authority: str = "RRM"

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

    def __bool__(self) -> bool:
        return self.valid

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CanonicalResourceBindingAuthority:
    """Select invocation bindings only when canonical RRM truth permits them."""

    def __init__(self, rrm, registry) -> None:
        self.rrm = rrm
        self.registry = registry
        self.last_resolution: ResourceBindingDecision | None = None
        self.last_revalidation: ResourceBindingRevalidation | None = None

    async def resolve(
        self, capability: str, *, preferred_kind: ExecutorKind | None = None
    ) -> ResourceBindingDecision:
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
            decision = ResourceBindingDecision(
                capability=capability,
                registration=entry,
                available=True,
                reason="eligible_binding",
                registered=True,
                rrm_eligible=True,
                binding_healthy=True,
                selected_binding=f"{entry.executor_kind.value}:{entry.executor_id}",
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
        )
        self.last_revalidation = result
        return result

    def _rrm_eligible(self, entry: CapabilityRegistration) -> bool:
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
