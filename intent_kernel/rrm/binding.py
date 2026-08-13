"""Canonical RRM-constrained execution-binding selection."""

from __future__ import annotations

from dataclasses import dataclass

from intent_kernel.orchestration.registry import CapabilityRegistration, ExecutorKind


@dataclass(frozen=True, slots=True)
class ResourceBindingDecision:
    capability: str
    registration: CapabilityRegistration | None
    available: bool
    reason: str
    authority: str = "RRM"


class CanonicalResourceBindingAuthority:
    """Select invocation bindings only when canonical RRM truth permits them."""

    def __init__(self, rrm, registry) -> None:
        self.rrm = rrm
        self.registry = registry

    async def resolve(
        self, capability: str, *, preferred_kind: ExecutorKind | None = None
    ) -> ResourceBindingDecision:
        entries = sorted(
            self.registry.discover(capability, executor_kind=preferred_kind),
            key=lambda item: (item.executor_kind.value, item.executor_id),
        )
        if not entries:
            return ResourceBindingDecision(capability, None, False, "binding_missing")
        for entry in entries:
            if not self._rrm_eligible(entry):
                continue
            if not await self.registry.available(entry):
                continue
            return ResourceBindingDecision(capability, entry, True, "eligible_binding")
        return ResourceBindingDecision(capability, None, False, "rrm_rejected_bindings")

    def revalidate(self, decision: ResourceBindingDecision) -> bool:
        return bool(
            decision.available
            and decision.registration is not None
            and self._rrm_eligible(decision.registration)
        )

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
